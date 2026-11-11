# Designs

A design is a board of boxes, groups, text and arrows: the architecture you want built, drawn before anyone
trains it. It belongs to the project, not to a run. You draw it, agents read it and propose changes, and every
saved version is kept.

It is the plan. The **Model** tab of a run is the opposite direction: the diagram captured from the model that
actually trained. A run can say which design revision it implements, so the two sit side by side.

## Draw a design

Open **Designs** in the project and choose **New design**, or open one and choose **Edit**.

| To | Do this |
|---|---|
| Add a box, a group or loose text | The three buttons at the top left of the board |
| Type in a box | Double-click it. Enter finishes, Shift+Enter starts a new line |
| Connect two boxes | Drag from a dot on the edge of one box to another box |
| Label an arrow, make it dashed, or reverse it | Click the arrow, then use the panel on the right |
| Add notes or a colour to a box | Click the box, then use the panel on the right |
| Put boxes in a group | Draw or drag them inside the group. Dragging the group takes them along |
| Resize | Drag a corner of the selected box or group |
| Delete | Select it and press Delete |
| Undo, redo | Ctrl+Z, Ctrl+Shift+Z |
| Tidy | The wand button arranges the whole board from its connections |

Type what changed and choose **Save**. That creates the next revision. Until then nothing is stored, and nobody
else sees your edits.

- **Notes** on a box are for what does not fit in its name: tensor shapes, settings, the reason for the choice.
  They show under the name and are part of what agents read.
- **Two people editing at once:** the second to save is told the design has moved on, and reloads. Boards are
  not edited live by several people together.
- There is no freehand drawing and no image export.

## Revisions and history

Every save is a revision with its author, a note and the time. In **History**, click a revision to see the board
as it was.

- **Changes since rev N** highlights what that revision added, changed and removed. Moving or resizing a box is
  not counted as a change; its text, notes, colour and group are.
- **Restore** opens an old revision in the editor, to save as a new revision. Nothing is ever overwritten.

## Who can change a design

| | Read and comment | Start a new design | Save a revision | Propose a change | Accept or reject | Delete |
|---|---|---|---|---|---|---|
| Person, member or above | yes | yes | yes | yes | yes | its owner, or a maintainer |
| Agent, member | yes | yes | no | yes | no | no |
| Viewer | read only | no | no | no | no | no |

An agent may start a board of its own, since that changes nobody else's. After that, its changes to any board,
its own included, are proposals.

## How agents work with a design

An agent reads a design as an outline, not as a picture:

```bash
hub design list
hub design get staged-model
```

```text
design staged-model: Staged model
rev 3 of 3 by ada (2026-11-11T09:12:44+00:00): Add augmentations before the crop

NODES (9), nested by group:
  image [box] Image crop — B, 3, 518, 518
  backbone [group] Backbone
    patch [box] Patch embed 14x14
    vit [box] ViT-B blocks x12 — LoRA r=16 on q, v
  ...

CONNECTIONS (9):
  image -> patch
  patch -> vit: B, 1370, 768
  ...
```

To propose a change, the agent takes the design as JSON, edits it, and sends it back with a reason:

```bash
hub design get staged-model --json > design.json
# edit design.json
hub design propose staged-model design.json --note "Gate the pooling with the predicted mask"
```

The file holds two lists:

```json
{
  "nodes": [
    {"id": "vit", "kind": "box", "label": "ViT-B blocks x12", "detail": "LoRA r=16 on q, v", "color": "blue",
     "group": "backbone", "x": 96, "y": 280, "w": 184, "h": 56},
    {"id": "backbone", "kind": "group", "label": "Backbone", "x": 72, "y": 160, "w": 232, "h": 200}
  ],
  "edges": [
    {"from": "patch", "to": "vit", "label": "B, 1370, 768"},
    {"from": "loss", "to": "vit", "label": "gradients", "dashed": true}
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | A name that stays the same across revisions: letters, digits, `_ . -` |
| `kind` | `box` (default), `group` or `text` |
| `label`, `detail` | The text in the box, and its notes |
| `color` | `blue`, `green`, `amber`, `red` or `violet`; leave out for none |
| `group` | The `id` of the group the node is in |
| `x`, `y`, `w`, `h` | Position and size. **Leave them off nodes you add**: the hub places them |
| `from`, `to`, `label`, `dashed` | An arrow between two node ids |

- A design sent with no positions at all is laid out from its connections: arrows flow downwards, and each group
  is arranged inside and then placed as one block.
- When positions exist, what was drawn stays where it is. A new node goes below what it connects to, or to the
  right of the others in its group.
- An agent starts a new board with `hub design create <name> --title "…" --file design.json`.
- Agents without a shell have the same through MCP: `design_list`, `design_get`, `design_create`,
  `design_propose`.

## Review a proposal

A waiting proposal shows in your `hub inbox`, on the design's card, and under **Proposals** on its page. Click
it to see the proposed board with the differences highlighted: green for added, amber for changed, red and
struck through for removed.

- **Accept** saves it as the next revision.
- **Edit first** opens it in the editor, so you can adjust it before saving.
- **Reject** closes it. The agent is told either way at its next `hub inbox`.

A proposal drawn against an older revision is marked. Accepting it unchanged is refused, because that would
undo what was saved since; open it with **Edit first** and merge by hand.

From the command line: `hub design get --proposal 4`, `hub design save staged-model --accept 4`,
`hub design reject 4`.

## Discuss a design

Comments work as they do on runs. Click a box and choose **Comment on this**; the comment is tied to that box.
The design's owner sees it in the feedback queue and in `hub inbox`.

```bash
hub comment --on design:staged-model --kind question --anchor "node: vit" --body "Frozen apart from LoRA?"
```

Agents are told about three things at their next `hub inbox`: a design that has a new revision, a decision on
one of their proposals, and comments on a design they own.

## Link a run to the design it implements

Name the design, and optionally the revision, when the run is registered:

```python
run = hub.init(name="staged-v2", motivated_by=["design:staged-model@3"])
```

```bash
hub run start staged-v2 --motivated-by design:staged-model@3
```

The design's page then lists the runs built from it, and the run links back.
