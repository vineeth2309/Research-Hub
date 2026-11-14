# Datasets and reviews

When many runs are evaluated on the same data, the interesting questions are about the samples, not the runs.
Which samples do most models get wrong? Where do the models split? Which ones does every model pass with high
confidence? **Datasets** in the sidebar answers them: one tile per sample of an eval set, with what every chosen
run made of it, and a place for a person to review the samples that matter. Nothing needs logging beyond the
per-sample results your runs already send ([docs/logging.md](logging.md#per-sample-results)).

## Open it

Pick an eval set at the top. A set appears as soon as one run has logged it. By default every finished run that
logged the set is chosen, each read at its last logged checkpoint. **Runs** opens a picker:

- filter by owner or verdict, find a run by name, and add or remove the ones shown;
- **save a selection** under a name ("classifiers", "W0 seeds") to come back to it. Saved selections are kept in
  your browser;
- each run shows when its results were last logged.

**Group seeds** puts runs named `<arm>-s<seed>…` side by side as seeds of one arm, in the strip on every tile and
in the sample table. No tagging is needed; runs that do not follow the pattern are their own arm.

## Find the samples that matter

The **Show** row has one-click presets, each with its count among the runs you chose:

| Preset | The samples where |
|---|---|
| Most runs wrong | more than half of the runs are wrong |
| Every run wrong | all of them are |
| Runs split | between a quarter and three quarters are wrong |
| Every run right | none is wrong (sorted by score, these are the confident cases) |
| One run wrong / right | exactly one run differs from all the others; pick which run |

Presets need truth. A run is wrong on a sample when its logged `outcome` is anything but `correct` or `unscored`.

The **Filter** row narrows by the true class, by every fact of the set (several values of one filter are OR-ed,
different filters AND-ed), by text in the sample id or any fact, and by **runs predicting a class**: pick a class
and how many runs must predict it ("at most 3 runs say normal"). That one also works for sets without truth.

Sort by most runs wrong, most disagreement, highest mean of a number in `pred`, widest spread, or highest mean
score. When the rows carry several numbers in `pred` (severity, value, depth), **Number** chooses which one the
mean and spread are of.

## What each tile and panel shows

- **Tile:** the image, the true class, one coloured cell per run (green correct, red missed or wrong, orange false
  alarm), a line such as "missed 15 of 24", the mean and spread of the chosen number, the two most common
  predicted classes, and the review badge once reviewed. Without truth the cell colour is the predicted class.
- **Samples by number of runs wrong:** a histogram over the filtered samples; the first bar is the samples every
  run gets right, cut off so the rest can be read.
- **Where most runs are wrong:** the samples that most runs get wrong, grouped by any fact.
- **Run × run agreement:** how often two runs are both right or both wrong (or, without truth, predict the same
  class). Hover a cell for the pair.
- **Export CSV** writes the filtered list with the aggregates and the current reviews, for building hard-case sets.

Clicking a tile opens the sample: a large image with the layer and box controls of the run you choose, the
facts, and a table of every run's predicted class, number, score and outcome, linked to the run.

## Review samples

A review is a person's judgement of **a sample, not of a run**. It is stored with the eval set and the sample id,
so it counts for every run on the set, today's and tomorrow's. Open a sample to review it:

| Field | Values |
|---|---|
| **Category** | critical defect / graded defect / unsure |
| **Difficulty** | easy / borderline / tough |
| **Class** | one of the classes of the set (true and predicted, from every run on it) |
| **Severity** | a number from 0 to 10 |
| **Bad image** | a checkbox: leave the sample out of scoring and training lists |
| **Comment** | free text |

Every field is optional. The class `Healthy` (or any negative class: normal, ok, good, none, background,
negative) means "not a defect".

- **Keys:** `1` to `3` set the category, `4` to `6` the difficulty (the same key again clears it), `b` toggles bad
  image, `c` goes to the comment, `s` or Ctrl+Enter saves, ← and → save a changed review and move to the
  previous or next sample.
- **Label is right** (`y`): saves the sample's own label as your review, class and severity, marks it as
  confirmed, and moves on. Most reviews confirm what is shown, so that is one keystroke; edit only where you
  disagree. The label is the set's truth; for samples without truth the project can name the facts that carry
  the deployed class and severity (below).
- **Append-only.** Saving again replaces the current review and keeps the earlier ones, listed under the panel
  with who wrote them and when. **Clear review** saves an empty review, which takes the review back. Nothing is
  ever written to labels, facts or datasets.
- **What was on screen is stored** with each review: the label and every selected run's predicted class and
  number. Later, "he agreed" can be told from "he typed the same thing".
- **Only people write reviews.** Members and above, signed in as a person; agents read them.
- The list does not move while you review: a sample you reviewed stays where it is until you close the sample,
  then the page reads the list again (so under "Not reviewed" it drops out).

### Using the reviews

- **Review row:** not reviewed, reviewed, bad image, and filters on the reviewed class, category, difficulty,
  reviewer and a severity range. The counts ignore the review filters, so "170 not reviewed" is what is left;
  "70 of 240 reviewed in this filter" is the progress. They combine with every preset and fact filter, so a
  review queue is a filter: for example "Runs split" + "Not reviewed".
- **Runs against your reviews:** for each run, over the reviewed samples that have a class and are neither bad
  image nor unsure: **agrees** (the run rejects what you found a defect and passes what you found fine), **false
  call** (it rejects a sample you found fine) and **miss** (it passes a defect). A run passes a sample when its
  predicted class is a negative class. The same verdict is on every row of the sample table.
- **A new run is scored automatically** against the reviews already given. Reviews do not need repeating, and
  the queue refills only with samples nobody has judged.

### Settings

What a category or difficulty is called, and where the label of a sample without truth lives, are project
settings, so the hub code names no dataset or defect. Set them as a maintainer (the settings are replaced as one
object, so `hub project set` reads the current ones first and keeps them):

```bash
hub project set my-project review='{"categories": ["critical defect", "graded defect", "unsure"],
  "difficulties": ["easy", "borderline", "tough"],
  "label_class_fact": "deployed_label", "label_severity_fact": "deployed_severity"}'
```

`unsure` is the category that leaves a sample out of scoring. With `label_class_fact` and `label_severity_fact`
set, **Label is right** works on samples that carry those facts and no truth.

## Read it from code

Agents read reviews and the aggregates; nothing here needs the browser.

```bash
hub review list --set parts@1.0:test                 # the current review of every reviewed sample
hub review list --set parts@1.0:test --csv           # for a hard-case list
hub review list --set parts@1.0:test --since 2026-11-14T12:00:00 --history
```

```
GET  /api/eval-sets                                  # every eval set and the runs that logged it
GET  /api/eval-sets/samples?set=…&runs=a,b,c         # a page of samples with every run's call and the review
     &preset=most_wrong|all_wrong|split|all_right|one_wrong|one_right  &run=<the one run>
     &class_true=…  &fact.<key>=v1,v2  &q=text  &pred_class=…&pred_min=…&pred_max=…
     &reviewed=0|1  &review_bad=1  &review_class=…  &review_category=…  &review_difficulty=…
     &review_by=…  &review_sev_min=…&review_sev_max=…
     &sort=wrong|disagree|value|spread|score|pred|sample  &value=<number in pred>  &limit=…&offset=…
     &compact=1                                      # aggregates only, up to 200,000 rows
GET  /api/eval-sets/summary?set=…&runs=…&by=<fact>   # preset counts, filter values, run × run agreement,
                                                     # review counts and each run against the reviews
GET  /api/eval-sets/reviews?set=…[&since=…][&history=1][&sample=…]
POST /api/eval-sets/review                           # people only: {set, sample, class, severity, category,
                                                     #   difficulty, bad_image, comment, confirmed, shown}
```

A call is `[outcome, predicted class, number, score]`, in the order of `runs` in the reply. Each row of the samples
call carries `review` (class, severity, category, difficulty, bad_image, comment, reviewer, created, confirmed),
or null. The MCP server has a `reviews` tool for agents without a shell.

## What to log so it works

- **Same eval set name and the same sample ids in every run.** A run appears on a set's page only if it logged
  that exact set name.
- **Facts belong to the sample and are shared by every run on the set; the first run to log one wins.** Put
  anything that differs from run to run in `pred`, `metrics` or `outcome`, not in `facts`. Keep facts stable:
  adding a sample, or adding or removing a fact, rebuilds the set's sample list on the next request.
- **The page counts the `outcome` each run logged.** To judge runs at an operating point rather than by class,
  log that verdict as `outcome`. For sets without truth send no `outcome` and put the run's decision in
  `pred.class`.
- **Name seeds `<arm>-s<seed>…`.**
- A finished run still takes rows logged with your own key, so a corrected `outcome` can be logged later at the
  same step with `hub run eval` or `research_hub.client.log_eval`; only the fields you send change.

## Speed and storage

Reading result rows one by one is slow on a busy disk, so what these pages need is packed into small files in
`summaries/` next to the database, one per run and checkpoint and one per eval set. They are named after the
version that every write raises, so a stale file is never read, they are rebuilt on demand, and they need no
backup. The first Datasets request that includes a run logged after the last one packs it, a few seconds for a
large set. After an upgrade from a release without them, the first start indexes the earlier results in the
background; until it has counted them, `GET /api/eval-sets` and the page answer "being indexed" (HTTP 503) and
nothing else waits. The reviews table is small and is read as it is.
