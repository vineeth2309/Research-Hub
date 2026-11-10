"""Capture a PyTorch model's architecture from one real training step: layers, shapes, connections and losses.

    run.watch(model)        # once, before training; the first step is recorded as it happens

Forward hooks record every layer call (shapes, parameters, activation statistics). The autograd graph PyTorch
builds anyway supplies the connections, including skip paths, functional operations and the way each loss is
reached, so no tracing or export is needed and models with Python control flow work. Hooks on the autograd nodes
during the step's own backward pass supply the shapes of the operations and every gradient norm. Nothing extra is
run: no additional forward or backward pass, and all hooks are removed after the first step.

What it cannot see: code under ``torch.no_grad()`` (those layers still appear, but not what connects them), and
compiled or scripted models whose layers do not call Python hooks.

Cost on a large model: the capture never copies weights, activations or gradients. Statistics are taken from a
strided sample of at most 65,536 values per tensor, so the extra memory is a few hundred kilobytes per layer
whatever the model's size. A graph with more than MAX_NODES nodes has its deepest blocks folded into single
nodes until it fits. Every hook is guarded: if one fails, capture stops and the training step carries on.
"""

from __future__ import annotations

import functools
import math
import re
import sys
import threading

import torch
from torch import nn

LOSS = re.compile(r"Loss$|^NllLoss|^BinaryCrossEntropy|^KlDiv|^CtcLoss")
LOSS_NAMES = {"NllLoss": "Cross-entropy", "BinaryCrossEntropyWithLogits": "Binary cross-entropy", "MseLoss": "MSE",
              "BinaryCrossEntropy": "Binary cross-entropy", "L1Loss": "L1", "SmoothL1Loss": "Smooth L1"}
INPUT_KEYS = {"img", "image", "images", "pixel_values", "input", "inputs", "x", "input_values", "inputs_embeds"}
MAX_NODES = 4000   # the hub accepts 5000; a 40-billion-parameter transformer has more operations than that
SAMPLE = 65536     # values read per tensor for activation and gradient statistics
KEEP = ("id", "kind", "name", "type", "group", "detail", "params", "in_shapes", "out_shape", "act_mean", "act_std",
        "grad_norm", "loss", "value", "dtype")


def _shape(t):
    return list(t.shape) if isinstance(t, torch.Tensor) else None


def _tensors(obj):
    if isinstance(obj, torch.Tensor):
        yield obj
    elif isinstance(obj, (list, tuple)):
        for o in obj:
            yield from _tensors(o)
    elif isinstance(obj, dict):
        for o in obj.values():
            yield from _tensors(o)


def _finite(v):
    return v if v is None or math.isfinite(v) else None


def _sample(t):
    """At most SAMPLE values of a tensor, evenly spaced, as float32: a view plus a small copy, never a full one."""
    flat = t.detach().reshape(-1)
    return flat[::max(1, flat.numel() // SAMPLE)].float()


def _safe(hook):
    """A hook that fails must not fail the training step: capture is abandoned instead."""
    @functools.wraps(hook)
    def guarded(self, *args):
        if self.broken:
            return None
        try:
            return hook(self, *args)
        except Exception as e:  # including out-of-memory raised while reading statistics
            self.broken = f"{type(e).__name__}: {e}"
            self.close()
            return None
    return guarded


def _deep(work):
    """Run ``work`` on a thread with a large stack: the walk recurses once per operation on the longest path,
    which is thousands of frames for a deep transformer."""
    box: dict = {}

    def target():
        try:
            box["value"] = work()
        except BaseException as e:  # handed back to the caller's thread
            box["error"] = e

    limit, stack = sys.getrecursionlimit(), threading.stack_size()
    try:
        threading.stack_size(512 * 1024 * 1024)
    except (ValueError, RuntimeError):  # the platform refuses: stay on this thread with a modest limit
        sys.setrecursionlimit(max(limit, 20000))
        try:
            return work()
        finally:
            sys.setrecursionlimit(limit)
    try:
        sys.setrecursionlimit(1_000_000)
        thread = threading.Thread(target=target, name="hub-model-graph")
        thread.start()
        thread.join()
    finally:
        threading.stack_size(stack)
        sys.setrecursionlimit(limit)
    if "error" in box:
        raise box["error"]
    return box.get("value")


class Trace:
    """Records one forward pass of ``model``; ``prepare`` and ``finish`` around the backward pass complete the graph."""

    def __init__(self, model: nn.Module, track_inputs: bool = False, leaf_types=(nn.MultiheadAttention,)):
        self.model = model
        self.nodes: dict[str, dict] = {}
        self.edges: set[tuple[str, str]] = set()
        self.producer: dict = {}       # autograd node -> the layer whose output it is
        self.fn_of: dict[str, object] = {}  # graph node -> autograd node, for the backward hooks
        self.inputs_of: dict[str, list] = {}  # layer -> (autograd node, tensor id, shape) of each input
        self.inputs: dict = {}         # autograd node or tensor id of a model input -> its node
        self.made: dict[int, str] = {}  # id of an output tensor without history (made under no_grad) -> its layer
        self.passthrough: dict = {}    # layer that returned its input untouched -> (the layer before it, autograd node)
        self.scope: dict = {}          # autograd node of a functional op -> the innermost block it ran inside
        self.blocks: dict[str, str] = {}  # block name -> its class
        self.calls: dict[str, int] = {}
        self.stack: list[str] = []     # blocks currently running, innermost last
        self._pending: dict[str, list] = {}
        self._entered: dict[str, set] = {}
        self._hooks: list = []
        self._grad_hooks: list = []
        self.broken = ""               # why capture was abandoned, if it was
        # One module object can sit in several places (Ultralytics shares a single SiLU between all its Conv
        # blocks), so a call is named after the place it was called from: the block running at that moment.
        self.names: dict[int, list[str]] = {}
        for name, module in model.named_modules(remove_duplicate=False):
            self.names.setdefault(id(module), []).append(name)
        whole = ""  # the module currently being treated as one layer although it has parts (named_modules is depth-first)
        for name, module in model.named_modules():
            if whole and name.startswith(whole + "."):
                continue
            if name and (not list(module.children()) or isinstance(module, leaf_types)):
                whole = name if isinstance(module, leaf_types) else ""
                self._hooks += [module.register_forward_pre_hook(self._pre), module.register_forward_hook(self._post)]
            else:  # a block, or the model itself: remember which functional ops ran inside it
                self._hooks += [module.register_forward_pre_hook(self._enter), module.register_forward_hook(self._leave)]
        if track_inputs:
            self._hooks.append(model.register_forward_pre_hook(self._track, with_kwargs=True))

    def close(self):
        for hook in self._hooks:
            hook.remove()
        self._hooks = []

    # ------------------------------------------------------------- forward
    def input(self, name: str, tensor: torch.Tensor) -> torch.Tensor:
        """Declare a model input by hand; pass the returned tensor to the model."""
        if not tensor.is_floating_point() or not torch.is_grad_enabled():
            self.inputs[id(tensor)] = self._input_node(name, tensor)
            return tensor
        copy = tensor.detach().requires_grad_(True).clone()  # a non-leaf, so in-place ops in the model keep working
        self.inputs[copy.grad_fn] = self._input_node(name, tensor)
        return copy

    def _input_node(self, name, tensor) -> str:
        node = f"input:{name}"
        self.nodes[node] = {"id": node, "kind": "input", "name": str(name), "type": "Input", "out_shape": _shape(tensor),
                            "dtype": str(tensor.dtype).replace("torch.", "")}
        return node

    @_safe
    def _track(self, module, args, kwargs):
        """Make the model's float inputs visible to autograd for this one step, so layers before the first
        trainable parameter are connected too."""
        def swap(value, label, top):
            if isinstance(value, torch.Tensor):
                return self.input(label, value) if value.is_floating_point() and value.grad_fn is None else value
            if top and isinstance(value, dict):  # a batch dict: only its image-like entries, never the targets
                return {k: swap(v, k, False) if k in INPUT_KEYS else v for k, v in value.items()}
            return value
        if not (self.model.training and torch.is_grad_enabled()):
            return None
        names = ["input"] if len(args) == 1 else [f"input {i + 1}" for i in range(len(args))]
        return (tuple(swap(a, n, True) for a, n in zip(args, names)),
                {k: swap(v, k, False) if k in INPUT_KEYS else v for k, v in kwargs.items()})

    def _here(self, module) -> str:
        names = self.names[id(module)]
        if len(names) > 1 and self.stack:
            for name in names:
                if name.rpartition(".")[0] == self.stack[-1]:
                    return name
        return names[0]

    @_safe
    def _enter(self, module, args):
        name = self._here(module)
        self.stack.append(name)
        self.blocks[name] = type(module).__name__
        self._entered[name] = {t.grad_fn for t in _tensors(args)}

    @_safe
    def _leave(self, module, args, output):
        name = self.stack.pop()
        before, seen = self._entered.pop(name, set()), set()
        todo = [t.grad_fn for t in _tensors(output)]
        while todo:  # inner blocks finish first, so the first scope recorded for an op is the innermost
            fn = todo.pop()
            if fn is None or fn in seen or fn in before or type(fn).__name__ == "AccumulateGrad":
                continue
            seen.add(fn)
            node = self.producer.get(fn)
            while node in self.passthrough and self.passthrough[node][0]:
                node = self.passthrough[node][0]  # look through layers that returned their input untouched
            if node is not None and node not in self.passthrough:
                todo += [f for f, _, _ in self.inputs_of.get(node, [])]
            else:
                self.scope.setdefault(fn, name)
                todo += [f for f, _ in fn.next_functions]

    @_safe
    def _pre(self, module, args):
        self._pending[self._here(module)] = [(t.grad_fn, id(t), _shape(t)) for t in _tensors(args)]

    @_safe
    def _post(self, module, args, output):
        name = self._here(module)
        n = self.calls[name] = self.calls.get(name, 0) + 1
        node = name if n == 1 else f"{name}#{n}"
        outs = list(_tensors(output))
        first = outs[0] if outs else None
        info = {"id": node, "kind": "module", "name": name, "type": type(module).__name__,
                "params": sum(p.numel() for p in module.parameters()), "detail": _describe(module),
                "in_shapes": [s for _, _, s in self._pending.get(name, [])], "out_shape": _shape(first),
                "group": name.rpartition(".")[0]}
        if first is not None and first.is_floating_point() and first.numel():
            values = _sample(first)
            info.update(act_mean=float(values.mean()), act_std=float(values.std()) if values.numel() > 1 else 0.0)
        self.nodes[node] = info
        self.inputs_of[node] = self._pending.pop(name, [])
        fed_by = {f for f, _, _ in self.inputs_of[node] if f is not None}
        for t in outs:
            if t.grad_fn is None:
                self.made[id(t)] = node
                continue
            if t.grad_fn in fed_by:  # the layer returned its input untouched (Dropout at p=0, Identity, ...)
                self.passthrough[node] = (self.producer.get(t.grad_fn), t.grad_fn)
            self.producer[t.grad_fn] = node
            self.fn_of.setdefault(node, t.grad_fn)

    # -------------------------------------------------- the autograd graph
    def _connect(self, node):
        """Link a layer to whatever feeds it, once."""
        if node in self._done:
            return
        self._done.add(node)
        if node in self.passthrough:
            before, fn = self.passthrough[node]
            if before:
                self._connect(before)
            sources = [before] if before else self._resolve(fn, raw=True)
        else:
            sources = [s for f, tid, shape in self.inputs_of.get(node, []) for s in self._resolve(f, tid, shape=shape)]
        for src in sources:
            if src != node:
                self.edges.add((src, node))

    def _resolve(self, fn, tensor_id=None, raw=False, shape=None) -> list[str]:
        """Graph nodes that produce the value behind an autograd node."""
        if fn in self.inputs:
            return [self.inputs[fn]]
        if fn is None:  # no history: a model input nobody declared (token ids, a frozen prefix's input)
            if tensor_id is None:
                return []
            if tensor_id in self.made:  # the output of a layer that ran without gradients
                self._connect(self.made[tensor_id])
                return [self.made[tensor_id]]
            if tensor_id not in self.inputs:
                node = f"input:{len(self.inputs) + 1}"
                self.nodes[node] = {"id": node, "kind": "input", "name": "", "type": "Input", "out_shape": shape}
                self.inputs[tensor_id] = node
            return [self.inputs[tensor_id]]
        if not raw and fn in self.producer:
            self._connect(self.producer[fn])
            return [self.producer[fn]]
        kind = type(fn).__name__
        if kind == "AccumulateGrad":  # a parameter
            return []
        if fn not in self._ops:
            node = f"op:{len(self._ops)}"
            self._ops[fn] = node
            self.fn_of[node] = fn
            op = re.sub(r"Backward\d*$", "", kind)
            self.nodes[node] = {"id": node, "kind": "op", "name": op, "type": op, "group": self.scope.get(fn, ""),
                                "outside": not self.scope.get(fn)}  # not inside any block: loss code or glue
            for nxt, _ in fn.next_functions:
                for src in self._resolve(nxt):
                    self.edges.add((src, node))
        return [self._ops[fn]]

    def prepare(self, total: torch.Tensor, terms: dict[str, torch.Tensor] | None = None) -> None:
        """Before ``total.backward()``: walk back from the loss and hook the autograd nodes for the backward pass."""
        self.close()
        if self.broken:
            raise RuntimeError(f"a hook failed during the forward pass ({self.broken})")
        self._done, self._ops = set(), {}

        def walk():
            for name, tensor in {**(terms or {}), "total": total}.items():
                for node in self._resolve(tensor.grad_fn):
                    self.nodes[node].update(kind="loss", loss=name, value=float(tensor.detach()))
        _deep(walk)
        named = dict(terms or {})
        for node in self.nodes.values():  # loss terms nobody named are recognised by what computed them
            scalar = node.get("out_shape") == [] or node["kind"] == "op"
            if node["kind"] in ("op", "module") and scalar and LOSS.search(node["type"]):
                label = LOSS_NAMES.get(node["type"], re.sub(r"(?<=[a-z])(?=[A-Z])", " ", node["type"]))
                node.update(kind="loss", loss=label, value=node.get("act_mean"))
                named[label] = None
        self._group_loss_code(named)
        self._grad_hooks = [fn.register_hook(self._grad(node)) for node, fn in self.fn_of.items()
                            if node in self._done or node.startswith("op:")]

    def finish(self) -> dict:
        """After the backward pass: the graph, ready for ``run.log_model_graph``."""
        for hook in self._grad_hooks:
            hook.remove()
        if self.broken:
            raise RuntimeError(f"a hook failed during the backward pass ({self.broken})")
        for held in (self.producer, self.fn_of, self.inputs_of, self.passthrough, self.scope, self._ops, self.inputs):
            held.clear()  # these point into the autograd graph: let go of it now
        self._grad_hooks = []
        used = {n for edge in self.edges for n in edge}
        nodes = []
        for node in self.nodes.values():
            if node["id"] in used:
                slim = {k: node[k] for k in KEEP if node.get(k) not in (None, "")}
                for key in ("act_mean", "act_std", "grad_norm", "value"):
                    if key in slim:
                        slim[key] = _finite(slim[key])
                nodes.append(slim)
        edges = [{"from": a, "to": b, "shape": self.nodes[a].get("out_shape")} for a, b in sorted(self.edges)]
        nodes, edges = _fold(nodes, edges, self.blocks, MAX_NODES)
        return {"model": type(self.model).__name__, "params": sum(p.numel() for p in self.model.parameters()),
                "trainable": sum(p.numel() for p in self.model.parameters() if p.requires_grad),
                "nodes": nodes, "edges": edges, "blocks": {k: v for k, v in self.blocks.items() if k}}

    def backward(self, total: torch.Tensor, terms: dict[str, torch.Tensor] | None = None) -> dict:
        """Run the backward pass yourself and get the graph: for capturing by hand, with named loss terms."""
        self.prepare(total, terms)
        total.backward()
        return self.finish()

    def _group_loss_code(self, terms):
        """Group the operations that are loss code, so the picture shows layers first and the loss as one block."""
        parents: dict[str, list] = {}
        children: dict[str, list] = {}
        for a, b in self.edges:
            parents.setdefault(b, []).append(a)
            children.setdefault(a, []).append(b)
        feeds: dict[str, list] = {}  # node -> the loss terms it contributes to
        for node in self.nodes.values():
            if node["kind"] == "loss" and node.get("loss") in terms:
                seen, todo = set(), [node["id"]]
                while todo:
                    for p in parents.get(todo.pop(), []):
                        if p not in seen:
                            seen.add(p)
                            todo.append(p)
                for p in seen:
                    feeds.setdefault(p, []).append(node["loss"])

        def before_a_layer(start):  # some layer still comes after this op: it is glue between layers, not loss code
            seen, todo = set(), [start]
            while todo:
                for c in children.get(todo.pop(), []):
                    if c not in seen:
                        if self.nodes[c]["kind"] == "module":
                            return True
                        seen.add(c)
                        todo.append(c)
            return False

        loose = [n for n in self.nodes.values() if n["kind"] == "op" and n.get("outside") and not before_a_layer(n["id"])]
        single: dict[str, list] = {}
        for node in loose:
            if len(feeds.get(node["id"], [])) == 1:
                single.setdefault(feeds[node["id"]][0], []).append(node)
        for term, members in single.items():
            if len(members) >= 3:
                for node in members:
                    node["group"] = f"computing {term}"
        shared = [n for n in loose if not n["group"]]
        if len(shared) >= 8:  # loss code whose terms cannot be told apart (written into one tensor in place)
            for node in shared:
                node["group"] = "loss computation"
            inside = {n["id"] for n in shared}
            for a, b in self.edges:  # a recognised loss in the middle of that code belongs inside the block
                if b in inside and self.nodes[a]["kind"] == "loss" and self.nodes[a].get("outside"):
                    self.nodes[a]["group"] = "loss computation"

    def _grad(self, node):
        @_safe
        def record(self, grad_inputs, grad_outputs):
            grad = next((g for g in grad_outputs if g is not None), None)
            if grad is not None:
                self.nodes[node].setdefault("out_shape", list(grad.shape))
                values = _sample(grad)  # the norm of a large gradient is estimated from the sample
                self.nodes[node]["grad_norm"] = float(values.norm()) * math.sqrt(grad.numel() / max(1, values.numel()))
        return functools.partial(record, self)


def _fold(nodes: list, edges: list, blocks: dict, limit: int) -> tuple[list, list]:
    """Fold the deepest blocks into one node each until the graph has at most ``limit`` nodes."""
    def depth(n):
        return n["group"].count(".") + 1 if n.get("group") and n["kind"] in ("module", "op") else 0

    while len(nodes) > limit:
        deepest = max(map(depth, nodes))
        if not deepest:
            break
        folded: dict[str, dict] = {}
        stands_for = {}
        for n in nodes:
            if depth(n) != deepest:
                stands_for[n["id"]] = n["id"]
                continue
            block = folded.setdefault(n["group"], {
                "id": f"block:{n['group']}", "kind": "module", "name": n["group"], "type": blocks.get(n["group"], "Block"),
                "group": n["group"].rpartition(".")[0], "params": 0, "layers": 0})
            block["params"] += n.get("params", 0)
            block["layers"] += n.get("layers", 1)
            if n.get("grad_norm") is not None:
                block["grad_norm"] = max(block.get("grad_norm", 0.0), n["grad_norm"])
            stands_for[n["id"]] = block["id"]
        by_id = {block["id"]: block for block in folded.values()}
        joined: dict[tuple, dict] = {}
        for e in edges:
            a, b = stands_for[e["from"]], stands_for[e["to"]]
            if a != b:
                joined.setdefault((a, b), {"from": a, "to": b, "shape": e.get("shape")})
                if a in by_id:
                    by_id[a].setdefault("out_shape", e.get("shape"))
        for block in folded.values():
            block["detail"] = f"{block['layers']} layers, folded to keep the diagram small"
            if block.get("out_shape") is None:
                block.pop("out_shape", None)
        nodes = [n for n in nodes if stands_for[n["id"]] == n["id"]] + list(folded.values())
        edges = list(joined.values())
    for n in nodes:
        n.pop("layers", None)
    return nodes, edges


def watch(model: nn.Module, on_graph, patience: int = 50) -> None:
    """Record the next training step of ``model`` and hand the finished graph to ``on_graph``.

    Hooks observe the first ``model(...)`` call in training mode; the first scalar ``.backward()`` after it supplies
    the connections and gradients. Training is never interrupted: if anything goes wrong the step runs as usual and
    a one-line warning is printed. After ``patience`` backward calls without a capture, it gives up quietly.
    """
    trace = Trace(model, track_inputs=True)
    original = torch.Tensor.backward
    seen = 0

    def stop():
        torch.Tensor.backward = original
        trace.close()

    def backward(self, *args, **kwargs):
        nonlocal seen
        seen += 1
        if trace.broken:
            stop()
            print(f"[hub] model graph not captured: {trace.broken}", file=sys.stderr)
            return original(self, *args, **kwargs)
        if not trace.producer or self.dim() != 0 or self.grad_fn is None:
            if seen >= patience:
                stop()
            return original(self, *args, **kwargs)
        stop()
        try:
            trace.prepare(self)
        except Exception as e:  # anything at all: a diagram must never cost a training run
            print(f"[hub] model graph not captured: {type(e).__name__}: {e}", file=sys.stderr)
            return original(self, *args, **kwargs)
        result = original(self, *args, **kwargs)
        try:
            on_graph(trace.finish())
        except Exception as e:
            print(f"[hub] model graph not logged: {type(e).__name__}: {e}", file=sys.stderr)
        return result

    torch.Tensor.backward = backward


def _describe(m) -> str:
    if isinstance(m, nn.modules.conv._ConvNd):
        size = "×".join(map(str, m.kernel_size))
        return f"{m.in_channels}→{m.out_channels}, {size}" + (f", stride {m.stride[0]}" if m.stride[0] != 1 else "")
    if isinstance(m, nn.Linear):
        return f"{m.in_features}→{m.out_features}"
    if isinstance(m, nn.modules.batchnorm._BatchNorm):
        return f"{m.num_features} channels"
    if isinstance(m, nn.LayerNorm):
        return "×".join(map(str, m.normalized_shape))
    if isinstance(m, nn.Embedding):
        return f"{m.num_embeddings}×{m.embedding_dim}"
    if isinstance(m, nn.MultiheadAttention):
        return f"{m.num_heads} heads, dim {m.embed_dim}"
    if isinstance(m, nn.Dropout):
        return f"p={m.p}"
    return ""
