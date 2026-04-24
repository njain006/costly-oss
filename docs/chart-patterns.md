# Cost Data Chart Patterns

A field guide for choosing, implementing, and avoiding chart types in Costly's
FinOps UI. Audience is mixed: data engineers who want to grok trend lines in
two seconds, finance who want budget vs. actual with a variance number, and
product managers who want "what is driving the growth."

The frontend is React + [Recharts 3.x](https://recharts.org) via shadcn/ui,
Next.js 15, Tailwind v4 (OKLCH tokens). Anything Recharts can't express, we
reach for [Observable Plot](https://observablehq.com/plot) (d3-based, low
ceremony, great for small multiples) or [visx](https://airbnb.io/visx) (lower
level, gives you a Sankey, Chord, Treemap primitive when you need it).

Throughout this doc, "$" means USD cost, "credits" means Snowflake compute
credits, "tokens" means LLM input/output/cache tokens. Ascii mockups assume a
monospace viewer.

Primary references:
- Claus Wilke, *Fundamentals of Data Visualization* — https://clauswilke.com/dataviz
- Observable Plot Gallery — https://observablehq.com/@observablehq/plot-gallery
- Recharts docs — https://recharts.org/en-US/examples
- visx gallery — https://airbnb.io/visx
- Datadog FinOps dashboards — https://www.datadoghq.com/blog/cloud-cost-management/
- CloudZero product screenshots — https://www.cloudzero.com/product/
- Vantage cost reports — https://www.vantage.sh
- Apache ECharts cookbook (great explanations even if you use Recharts) — https://echarts.apache.org/examples/en/index.html
- ColorBrewer — https://colorbrewer2.org
- WCAG 2.1 non-text contrast SC 1.4.11 — https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html

---

## 1. Temporal cost — daily / weekly / monthly trends

"How is spend changing over time, and is that change normal?" This is the
chart the dashboard opens on. Get it wrong and nothing else matters.

### 1a. Stacked area by platform

```
$   ┌─────────────────────────────────────────┐
    │                             ░░░░░░░░░░░░│  ← Anthropic
    │                  ░░░░░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓│
    │        ░░░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓████████████│  ← Snowflake
    │░░░░░░░░▓▓▓▓▓▓▓▓▓▓████████████▓▓▓▓▓▓▓▓▓▓▓│  ← AWS
    └─────────────────────────────────────────┘
     Mar 1                                 Mar 30
```

**When to use.** Showing total spend composition over time when you want both
the top line (total) *and* a rough sense of which platform is eating the
budget. Classic example: "show me March stack spend by vendor."

**When NOT to use.** When individual platform trends matter more than the
total. If Anthropic is $30/day and Snowflake is $3,000/day, Anthropic becomes
a pixel-thin stripe that nobody can read. Also bad with >7 series — the eye
can't track 10 colored bands. Another failure mode: if any series goes to zero
(connector disabled), the stack compresses and makes the remaining series
visually jump.

**Implementation (Recharts).**
```tsx
<AreaChart data={data}>
  <XAxis dataKey="date" />
  <YAxis tickFormatter={(v) => formatCurrency(v)} />
  <Tooltip />
  <Legend />
  <Area dataKey="aws"       stackId="1" fill={chart[0]} stroke={chart[0]} />
  <Area dataKey="snowflake" stackId="1" fill={chart[1]} stroke={chart[1]} />
  <Area dataKey="anthropic" stackId="1" fill={chart[2]} stroke={chart[2]} />
</AreaChart>
```
Critically, **order stacks largest-at-the-bottom**. The bottom series gets a
flat baseline and is the easiest to read; put your biggest cost-driver there,
smallest on top. Costly's `ChartPanel` currently preserves config order — we
should sort `yKeys` by total descending before rendering.

**Common mistakes.**
- Stacking in arbitrary config order instead of sorted-by-magnitude.
- Using `type="monotone"` on spiky cost data (it creates invented dips between
  points). Prefer `type="linear"` or `type="step"` for daily granularity.
- Full-opacity fills make it look like a painting. Use `fillOpacity={0.75}`
  and keep `stroke` at full opacity so the top of each band is crisp.

### 1b. Stacked bar (categorical time)

Same data, but each day is a discrete bar. Works better when the time axis is
inherently bucketed (weeks, months). A stacked bar for 90 daily points becomes
hatching — use area for long windows, bar for ≤30 buckets.

**Where stacked bar wins over stacked area:** when you want the reader to
compare discrete periods ("March 14 was 2x March 7"), not infer a continuous
trend. Also better for showing zero-days honestly — a missing bar is obvious,
a flat-bottomed area isn't.

### 1c. Line-per-platform (no stacking)

```
$   ┌─────────────────────────────────────────┐
    │         ╱╲                     ╱─ AWS    │
    │ ───────╱  ╲──────╱╲──────────        SF  │
    │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─       AI │
    └─────────────────────────────────────────┘
```

**When to use.** When trends of individual platforms matter more than the
total — e.g., "is our AI spend growing faster than our warehouse spend?"
Survives log-scale y-axis cleanly, which stacked area cannot.

**When NOT to use.** When there are >5 lines (spaghetti) or when series have
wildly different magnitudes on linear scale. For magnitude mismatches, switch
to log-scale y-axis, or to small multiples (section 5).

**Implementation.**
```tsx
<LineChart data={data}>
  <XAxis dataKey="date" />
  <YAxis scale="log" domain={["auto", "auto"]} />
  {platforms.map((p, i) => (
    <Line key={p} dataKey={p} stroke={chart[i]} dot={false} strokeWidth={2} />
  ))}
</LineChart>
```

### 1d. Calendar heatmap

```
       Mon Tue Wed Thu Fri Sat Sun
Wk 1 [ ░   ▒   █   █   ▓   ░   ░ ]
Wk 2 [ ▒   ▒   █   █   █   ░   ░ ]
Wk 3 [ ▒   █   █   █   █   ░   ░ ]
Wk 4 [ ░   ▒   █   █   █   ░   ░ ]
```

**When to use.** Detecting weekly or monthly seasonality — "our dbt runs are 4x on Tuesdays," or "did we run on weekends during the outage?"

**When NOT to use.** When precise values matter. Color encodes magnitude at ~5 bits — good for patterns, useless for "$342 vs $438."

**Implementation.** Not in Recharts. Observable Plot:
```tsx
Plot.plot({
  y: { domain: ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"] },
  color: { scheme: "blues", legend: true },
  marks: [Plot.cell(data, {
    x: (d) => d3.timeWeek.count(start, d.date),
    y: (d) => d.date.toLocaleDateString("en", { weekday: "short" }),
    fill: "cost", inset: 0.5, tip: true,
  })],
});
```
Or visx `HeatmapRect`. Use a sequential scale (`blues`, `viridis`) — never rainbow (non-monotonic perceptually).

### 1e. Anomaly overlay patterns

Three idioms, usually combined:

1. **Point annotations.** Recharts `<ReferenceDot />` at the spike with label: "Mar 14: Anthropic batch backfill."
2. **Confidence band.** Shaded rolling median ±2σ (or P10/P90 from a forecast) behind the actual line. Actual escaping band = anomaly. In Recharts, stack two `<Area>`s (upper then background-colored lower) or use visx `<AreaClosed>` with explicit `y0`/`y1`.
3. **Z-score bar shading.** Color each bar by |z| against 30d rolling mean: |z|>3 red, |z|>2 amber. Datadog's pattern — https://docs.datadoghq.com/monitors/types/anomaly/.

**Common mistakes.** Static thresholds drift with business growth — always compute bands from a rolling window. Don't use one-sided bands; underruns matter too (stalled pipeline, killed workload).

---

## 2. Compositional cost — where is the $ going right now

### 2a. Pie (and when to avoid)

```
      ╱───╲
   ╱─╱     ╲─╲
  │   47%    │   AWS
  │ ╲         │
  │  ╲   30%  │   Snowflake
   ╲  ╲_____╱─╲
    ╲_18%__5%_╱   Anthropic / other
```

**When to use.** 2–5 categories, one is dominant, you want a visceral "this is
half the pie" reaction. Board slide, executive summary.

**When NOT to use.** >5 slices, slices are close in magnitude, or you want the
user to compare two pies side-by-side. Humans can't angle-compare reliably
past ~5 slices. Never use a 3D pie, ever — the projection distorts the angles.

**Implementation.** Costly uses `<PieChart>` with `innerRadius=50` (donut,
which is slightly better than pie because comparing arc *length* at the outer
edge is easier than comparing wedge *angle*).

### 2b. Donut

Same as pie but with a hole. Put the total $ in the hole. That's the whole
point — a donut with nothing in the middle is a pie that's embarrassed.

```
      ╱───╲
   ╱─╱ $42K╲─╲
  │   total   │
  │  ╲ Mar  ╱ │
   ╲  ╲___╱──╲
    ╲________╱
```

**Implementation (Recharts).**
```tsx
<PieChart>
  <Pie data={data} dataKey="cost" innerRadius={60} outerRadius={90} paddingAngle={2}>
    {data.map((_, i) => <Cell key={i} fill={chart[i]} />)}
  </Pie>
  <text x="50%" y="50%" textAnchor="middle" dominantBaseline="middle">
    <tspan fontSize="28" fontWeight="700">$42K</tspan>
    <tspan x="50%" dy="1.4em" fontSize="12" fill="#64748b">Mar spend</tspan>
  </text>
</PieChart>
```

### 2c. Treemap (hierarchy)

```
┌──────────────────────────────┬──────────────┐
│                              │              │
│   Snowflake                  │  AWS         │
│   ┌───────────┬──────┐       │ ┌──────┐     │
│   │ COMPUTE_WH│ ETL_W│       │ │ S3   │     │
│   ├───────────┤      │       │ ├──────┤     │
│   │ REPORT_WH │      │       │ │ EC2  │     │
│   └───────────┴──────┘       │ └──────┘     │
├──────────────────────┬───────┴──────────────┤
│  Anthropic           │  dbt Cloud           │
└──────────────────────┴──────────────────────┘
```

**When to use.** Hierarchical composition — platform → service → resource
→ job. Treemap area scales linearly with cost, so your eye picks up
proportion immediately *and* the nesting preserves the hierarchy.

**When NOT to use.** Deep hierarchies (>3 levels). Tiny leaves become
unreadable slivers. Slicing a treemap by an extra attribute (e.g., environment)
is where people go wrong — use nested treemaps or sunburst instead, or just
two side-by-side treemaps.

**Implementation (Recharts 3.x).**
```tsx
import { Treemap } from "recharts";
<Treemap
  data={tree}
  dataKey="cost"
  stroke="#fff"
  fill="#6366F1"
  content={<CustomNode />}  // needed for labels on large leaves only
/>
```
Recharts' treemap is basic. For production-quality squarified layout with
hover drill-down, use visx (`@visx/hierarchy`'s `Treemap` + `treemapSquarify`
tiling). CloudZero's cost views are the gold-standard reference — see
https://www.cloudzero.com/product/.

**Treemap vs sunburst — why we prefer treemap.** Treemap uses area →
quantity (Weber-Fechner friendly). Sunburst uses angle → quantity, which works
for the innermost ring but degrades at the outer rings because angular area of
a sliver is non-intuitive. Sunburst wins only when the hierarchy is shallow
(2–3 levels) *and* the top level has few categories (say 4–6 platforms) — then
it looks beautiful. For Costly's platform → service → resource → query/model
depth-4 case, treemap is the right default. Claus Wilke agrees
(https://clauswilke.com/dataviz/nested-proportions.html).

### 2d. Sunburst

```
         ╱──────╲
       ╱  AWS    ╲
      │  ╱────╲   │
      │ │EC2│S3│  │
      │  ╲────╱   │
       ╲_________╱
```

**When to use.** You want to *visually express* that something is nested, not
just break it into a list. Good for 2–3 hierarchy levels with small branching
factor (≤6 per level).

**When NOT to use.** Deep trees, wide trees, anywhere you want to compare
cross-branch magnitudes. Not shipped in Recharts — use visx `<Partition>`
(https://airbnb.io/visx/docs/hierarchy#Partition) or Plot's `arc` mark.

### 2e. Bar + stacked segment

A horizontal bar per platform, where the bar length = total cost and internal
stacks = cost breakdown. Easiest-to-read compositional chart for dashboards
because it gives you both dimensions without any trig.

```
Snowflake ████████████░░░░░░░░░░   $18K    compute 78% | storage 22%
AWS       ███████░░░░░░░░░░░░░░░   $12K    EC2 60% | S3 30% | other 10%
Anthropic ████░░░░░░░░░░░░░░░░░░   $6K     input 40% | output 35% | cache 25%
```

**Implementation (Recharts horizontal stacked bar).**
```tsx
<BarChart data={data} layout="vertical">
  <XAxis type="number" />
  <YAxis dataKey="platform" type="category" width={100} />
  <Bar dataKey="compute" stackId="a" fill={chart[0]} />
  <Bar dataKey="storage" stackId="a" fill={chart[1]} />
  <Bar dataKey="egress"  stackId="a" fill={chart[2]} />
</BarChart>
```

### 2f. Marimekko (mosaic)

Like a stacked bar, but column widths are *also* variable — width = platform
share, height = within-platform breakdown. Reads as a 2D cost matrix.

**When to use.** Executive view of "platform share of budget AND
service-mix within each." Adobe, McKinsey decks use these constantly.

**When NOT to use.** Interactive dashboards. Marimekko is dense and needs
careful annotation; not friendly to hover tooltips. Not in Recharts — visx
has no native Marimekko either, so it's custom SVG or switch to Observable
Plot with `Plot.rectY` + manual width computation, or use the
[nivo Marimekko](https://nivo.rocks/marimekko/) component.

### 2g. Bubble packing (circle packing)

Circles of radius ∝ √(cost) packed into a container. Fun, spatial, a little
whimsical — great for landing pages and "here's your portfolio" visuals. Area
is the encoding (remember: r ∝ √cost so that area ∝ cost).

**When to use.** Overview with many small units that don't have strict
hierarchy. "All 127 dbt models ranked by monthly cost."

**When NOT to use.** When precise comparison matters. Humans under-estimate
area ratios for circles (Stevens' power law exponent ≈ 0.7).

**Implementation.** visx `<Pack>` (`@visx/hierarchy`). See
https://airbnb.io/visx/pack.

**Common mistakes across this section.**
- Encoding by diameter instead of area (doubles the apparent size ratio).
- Rainbow categorical palettes — use a designed categorical palette (see
  section 10), max 8 colors, with gray for "Other."
- Label-inside-slice that falls off a sliver. Always have a plan B: leader
  lines + external labels, or hide labels under a size threshold.

---

## 3. Flow cost — attribution and chargeback

"Which pipeline, running on which compute, cost which team?"

### 3a. Sankey

```
  dbt project            warehouse           team
  ┌─────────┐           ┌─────────┐        ┌──────┐
  │marts/   ├──────────▶│XL_WH    ├──────▶│ Data │
  │finance  │           │         │       └──────┘
  │         ├────┐      └─────────┘        ┌──────┐
  └─────────┘    ╲                   ┌───▶│Mktg  │
  ┌─────────┐     ╲    ┌─────────┐  ╱     └──────┘
  │staging/ ├──────▶──▶│M_WH     ├─┘
  │ad_spend │          └─────────┘
  └─────────┘
```

**When to use.** Cost-attribution with 2–4 dimensions — source → warehouse
→ team, or model → endpoint → user-segment. Sankey visually encodes
*where the money is flowing*, which is exactly what chargeback conversations
are about. Kolena and CloudZero both leverage Sankey for this
(https://www.cloudzero.com/blog/).

**When NOT to use.** >50 flows (becomes spaghetti). When edges can go backward
(it's acyclic by definition). When the reader cares about magnitudes — link
width encodes cost, but comparing widths isn't as accurate as a bar.

**Implementation.** Recharts has no Sankey. Options:
1. [`@visx/sankey`](https://airbnb.io/visx/docs/sankey) — integrates d3-sankey.
   Preferred for production.
2. [`react-plotly.js`](https://plotly.com/javascript/sankey-diagram/) — gives
   you a working Sankey with ~10 lines, but you're loading ~3MB of Plotly.
3. Apache ECharts via `echarts-for-react` — compact Sankey.

Sketch with visx:
```tsx
import { Sankey } from "@visx/sankey";

<Sankey
  width={900}
  height={500}
  nodes={nodes}  // [{name: "marts.finance"}, {name: "XL_WH"}, {name: "Data"}]
  links={links}  // [{source: 0, target: 1, value: 1200}, ...]
  nodeWidth={15}
  nodePadding={10}
/>
```

### 3b. Alluvial

Sankey's cousin, specifically for categorical × categorical × time. Same
primitive (d3-sankey), different mental model — "how did category membership
shift between March and April?" E.g., "Top 100 queries: did their warehouse
assignment change month-over-month?"

**When to use.** Migration / re-attribution stories. "Reassigning these 30
models from warehouse A to B is the 12k/mo we talked about."

### 3c. Chord diagram

```
         AWS
        ╱─╲
       ╱   ╲
      ╱╲───╱╲
  SF ╱  ╲_╱  ╲ dbt
     ╲  ╱ ╲  ╱
      ╲╱───╲╱
       ╲   ╱
        ╲_╱
     Anthropic
```

**When to use.** Flows *between* peer categories — team ↔ team cross-charges,
region ↔ region data-egress cost. Symmetric or asymmetric pairwise flows.

**When NOT to use.** Almost always in FinOps. Chord is a stunning chart for
genomics and migration, but data-cost flows are overwhelmingly asymmetric
(costs flow from source → consumer), for which Sankey is clearer.

**Implementation.** visx has no chord. Use `d3-chord` directly or Apache
ECharts.

**Common mistakes.**
- Sankey link colors that don't match the source node color. Readers trace
  flows by color; breaking the color chain ruins the chart.
- Sorting Sankey nodes alphabetically. Always sort by magnitude (largest
  first). d3-sankey does this automatically if you feed it right.
- Aggregating flows below some floor into "Other" without saying so.

---

## 4. Distribution — outliers and concentration

Query cost is a fat-tailed distribution. The top 10 queries are usually 60%+
of compute spend. Distribution charts are how you make that visible.

### 4a. Histogram

```
count
  │  ██
  │  ██
  │  ██ ██
  │  ██ ██ ██              ░░░░░░░░░░
  └──██─██─██─░─░─░─░─░─░─░─░─░─░────▓──────
     $0  $1  $5  $10  $50  $100+       $2,400 (one query!)
```

**When to use.** Answering "what's a normal query cost?" Default for any
summary of a continuous cost variable.

**When NOT to use.** With few data points (<50) — use a strip plot. When the
tail is what you care about (it is, for cost). Pair histogram with Pareto
chart (4e) for the full picture.

**Implementation.** Recharts has no native histogram. Bucket your data in JS:
```tsx
const buckets = d3.bin().thresholds(20)(queries.map(q => q.cost_usd));
<BarChart data={buckets.map((b, i) => ({ bin: `$${b.x0}-${b.x1}`, n: b.length }))}>
  <Bar dataKey="n" />
</BarChart>
```
Or use Plot's native `Plot.rectY({...}, Plot.binX(...))`.

**Log-scale trick.** Query cost spans 4+ orders of magnitude. Bin in log
space: `d3.bin().thresholds(d3.scaleLog().ticks(20))`. Without this, the
histogram is a single tall bar at $0 and a flat line everywhere else.

### 4b. Box plot

```
              ┌──┬─────┐
    ├────────┤  │     ├───────────       ° ° ° °  (outliers)
              └──┴─────┘
      Q0    Q1 med Q3         Q4
```

**When to use.** Comparing query cost distributions across warehouses / teams. "Is marketing's p95 higher than finance's?"

**When NOT to use.** PM-facing dashboards without an explainer ("box = middle 50%"). Engineers read them fine.

**Implementation.** `Plot.boxY()` or visx. Recharts needs ComposedChart with Bar + Line + ErrorBar — ugly; prefer Plot.

### 4c. Violin

Box plot + density. Shows *shape*, not just quantiles — bimodal distributions hide in box plots but pop in violins. Use when two populations are suspected (cheap frequent queries vs rare expensive ones). `Plot.densityY()`, visx `@visx/shape` + KDE, or ECharts boxplot+density overlay.

### 4d. Strip plot (dot plot)

```
$0 —•••• •  •    •   •            •                 • •  —→ $2,400
```

Each query is a dot. Great for ≤500 points where individuals stay identifiable (hover → SQL). >2k points overplot — switch to histogram or violin.

### 4e. Pareto chart (80/20)

```
$                                              cum %
  │█                                       ___100%
  │█                                   ___/   80%
  │█ █                             __/
  │█ █ █                        __/         
  │█ █ █ █ █ ██ ██ ██ ██ ██ ██ /              20%
  │___________________________________________0%
    q1 q2 q3 q4 ... → queries sorted by cost
```

**When to use.** The *canonical* FinOps distribution chart. Sort queries (or
models, or warehouses) descending by cost, bar the cost, line the cumulative
% of total. The chart literally shows "20% of queries = 80% of cost" when
that's true.

**When NOT to use.** When the distribution is *not* skewed (rare in cost
data). The chart falls flat on uniformly distributed data.

**Implementation (Recharts ComposedChart).**
```tsx
<ComposedChart data={sortedByCost}>
  <XAxis dataKey="query_id" hide />
  <YAxis yAxisId="left" />
  <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
  <Bar yAxisId="left" dataKey="cost" fill="#6366F1" />
  <Line yAxisId="right" dataKey="cumPct" stroke="#DC2626" dot={false} strokeWidth={2} />
  <ReferenceLine yAxisId="right" y={80} stroke="#64748b" strokeDasharray="4 4" />
</ComposedChart>
```

### 4f. Lorenz curve + Gini

The theoretically purest "concentration" chart. X axis = cumulative share of
*things* (queries), Y axis = cumulative share of *cost*. Diagonal = perfect
equality. Area between curve and diagonal → Gini coefficient.

```
100% cost │        ╱
          │      ╱  ← perfect equality
          │    ╱  
          │  ╱_________  ← your curve
          │╱─          `─._
          └─────────────────→ 100% queries
```

**When to use.** Reporting concentration as a single number over time. Is
Costly's query-cost concentration getting worse? Gini went from 0.62 to 0.78
→ a few queries are taking over.

**When NOT to use.** User-facing dashboards. Lorenz is an economist's chart;
most product audiences find Pareto more intuitive.

**Implementation.** Plot line with manual cumulative computation, or visx
`<LinePath>`. Nothing native.

**Common mistakes.**
- Not sorting before plotting Pareto. You'd think this is obvious. It isn't.
- Linear y-axis on fat-tailed distributions. Log scale, or bust.
- Showing mean cost as the central tendency. Use median + p95. Means lie on
  skewed distributions.

---

## 5. Correlation — cost vs business signal

### 5a. Scatter

```
 cost
   │                                     °
   │                              °°
   │                        °  °
   │                  °  °° °
   │          °  °°°°°°°
   │    °°°°°°°°°
   │°°°°°
   └────────────────────────────────→ rows_scanned
```

**When to use.** Cost vs any numeric business signal: rows processed,
latency, quality score, model size. The pattern in the cloud tells you if
your cost is driven by volume (steep line) or by something else (cloud of
noise, constant, or weird clusters = probably a few misbehaving queries).

**When NOT to use.** When both axes are categorical (use a heatmap). When
n > 5k (overplot; use density contours or hexbin — Plot's `Plot.hexbin()`).

**Implementation (Recharts).**
```tsx
<ScatterChart>
  <XAxis dataKey="rows" type="number" scale="log" />
  <YAxis dataKey="cost" type="number" scale="log" />
  <Scatter data={queries} fill="#6366F1" fillOpacity={0.4} />
  <ReferenceLine y={expectedCost(x)} stroke="#DC2626" strokeDasharray="4 4" />
</ScatterChart>
```

Annotate the regression line. Anything far above the line is a query that
costs more than its workload warrants — candidate for optimization.

### 5b. Small multiples

```
 dev                staging              prod
┌──────────┐     ┌──────────┐     ┌──────────┐
│   ╱      │     │   ╱      │     │       ╱ │
│  ╱       │     │  ╱       │     │      ╱  │
│ ╱        │     │ ╱        │     │     ╱   │
└──────────┘     └──────────┘     └──────────┘
```

**When to use.** Comparing the same chart across an ordinal or categorical
dimension — environment, region, team. "Our dev spend tracks prod at 20%,
but staging is tracking at 60% — that's weird." Edward Tufte's favorite
idiom for a reason.

**Implementation.** Plot has `fx:` / `fy:` faceting — one-liner. visx has
`<GridRows>` with manual layout. Recharts: you render the chart once per
facet in a CSS grid; works fine for ≤6 facets.

### 5c. Bubble chart

Scatter with a third dimension encoded as bubble size (volume), optional
fourth as color (segment). Classic Gapminder construction.

**When to use.** Cost (x) × quality / success-rate (y) × volume (size). Lets
you see "this cheap model has high quality but low volume — we don't
actually use it much; this expensive model has high volume and decent
quality — it's the workhorse." Multi-model comparison. Model-arbitrage
storytelling.

**Implementation (Recharts).**
```tsx
<ScatterChart>
  <XAxis dataKey="cost_per_1k_tokens" type="number" />
  <YAxis dataKey="quality_score" type="number" domain={[0, 1]} />
  <ZAxis dataKey="monthly_calls" range={[40, 400]} />  // bubble size
  <Scatter data={models} fill="#6366F1" />
  <Tooltip content={<CustomTooltip />} />
</ScatterChart>
```

**Common mistakes.**
- Encoding by bubble *diameter* instead of area (recharts' `ZAxis` `range`
  is the area, which is correct — but verify).
- Too many axes (>4 encodings). Drop color, drop shape. Less is more.

---

## 6. Comparison — budget vs actual, period over period

### 6a. Bullet chart

```
  target
     ▼
  ├──╫────╫────╫────╫────╫──┤   actual: ▓▓▓▓▓▓▓▓▓▓
    poor good great
```

**When to use.** Single-metric gauge replacement with three reference zones (bad/ok/good) + actual + target crossline. Dense; fits in a small card. Stephen Few's spec: https://perceptualedge.com/articles/misc/Bullet_Graph_Design_Spec.pdf.

**Implementation.** Recharts ComposedChart: stacked `<Bar>`s (lightness-ramped grays for ranges) + a thin `<Bar>` for actual + `<ReferenceLine>` for target.

### 6b. Deviation bars

```
   budget
     │
  ─────────────────── 0
     │
   AWS    +$2,100  ▓▓▓▓▓▓      (over)
   SF     −$800    ░░          (under)
   Anth   +$450    ▓▓          (over)
```

**When to use.** Variance reporting — how far is each platform from budget? Positive up, negative down, zero centered. Color asymmetry (red over / green under) reads at a glance. Recharts: `<Bar dataKey="delta">` with conditional `<Cell fill>` per-row.

### 6c. Slope graph

```
       Feb              Mar
AWS   $8k   ─────────── $11k     ▲ +37%
SF    $15k  ─────────── $13k     ▼ -13%
Anth  $3k   ─────────── $6k      ▲ +100%
```

**When to use.** 2–3 time periods, many categories. Annotate endpoints with values + % change. >3 periods → line chart instead. `Plot.line()` or Recharts `<LineChart>` with two x values. Tufte reference: https://www.edwardtufte.com/bboard/q-and-a-fetch-msg?msg_id=0003nk.

### 6d. Overlaid period-over-period

Two series on a line chart: `current` and `prior` (shifted to align dates). Prior dashed + lighter. Optional fill between lines for the delta. The classic "this month vs last month" overlay.

### 6e. Waterfall

```
Start     +AWS     −SF savings   +Anth    End
████      ████                            ████
  │       │         ─────                   │
  │       │         ─────                   │
  │       │                                 │
  │       │                      ██         │
  $30k    $33k      $31k                   $34k
```

**When to use.** Variance attribution: "budget was $30k, we ended at $34k;
what happened?" AWS up $3k, SF optimization saved $2k, Anthropic up $3k.
The classic CFO chart for explaining a number.

**Implementation.** Recharts has no native waterfall. Hack with
`ComposedChart` + `<Bar>` with `stackId` and invisible base bars, or use
Apache ECharts (`type: 'bar'` with `stack` and transparent base). visx:
`@visx/shape` + manual.

### 6f. Gauge — when to use, when to avoid

```
      ╱──────────╲
    ╱              ╲
   ╱     73%        ╲
  │   ▓▓▓▓▓▓▓░░░░    │
   ╲                ╱
     ╲─   ─    ─  ╱
       0         100
```

**When to avoid.** Gauges look FinOps-y but carry ~1 bit of information that fits in a number with a chevron. Avoid on multi-metric dashboards.

**When gauges win.** A single bounded 0–100% metric with meaningful zones — cache-hit-rate (0–40% alarming / 40–80% ok / 80–100% great), warehouse utilization, test-coverage. Recharts `<RadialBarChart>` half-dial (`startAngle=180 endAngle=0`) or visx `<Arc>`.

**Common mistakes across section 6.** Unlabeled target lines; red/green-only encoding (add +/− text or shape); waterfall bars that don't tie — double-check the final equals start + Σ deltas.

---

## 7. Forecast / projection

### 7a. Fan chart (P10/P50/P90)

```
$    ┌────────────────────────────────┐
     │                   ░░░░░░░ P90  │
     │                ░░░▒▒▒▒▒▒▒      │
     │ actual ────▶▒▒▒▓▓▓▓▓▓▓▓ P50    │
     │             ░░░▒▒▒▒▒▒▒▒        │
     │                   ░░░░░░░ P10  │
     └────────────────────────────────┘
     past       ◂today◂        future
```

**When to use.** Projecting spend 30/60/90 days out with stated uncertainty.
Central P50 line + shaded P10–P90 band + optional inner P25–P75 band. The
fan widening over the forecast horizon is *information* — it tells the
reader the model doesn't know.

**When NOT to use.** When you don't actually have a probabilistic model.
Plotting "actual ± 10%" as a fake confidence band is misleading. Either use
a real quantile forecast (Prophet, NeuralProphet, a Bayesian GLM) or
switch to discrete scenarios (7c).

**Implementation (Recharts).** Layer two `<Area>`s and a `<Line>`:
```tsx
<ComposedChart data={forecast}>
  <Area dataKey="p90" stackId="band" fill="#C7D2FE" stroke="none" fillOpacity={0.4} />
  <Area dataKey="p10" stackId="band" fill="#fff"    stroke="none" fillOpacity={1.0} />
  <Line dataKey="p50" stroke="#4F46E5" strokeWidth={2} dot={false} />
  <Line dataKey="actual" stroke="#111827" strokeWidth={2} dot={false} />
  <ReferenceLine x={today} stroke="#64748b" strokeDasharray="4 4" label="today" />
</ComposedChart>
```
Cleaner alternative in visx: `<AreaClosed>` with explicit `y0` + `y1`. See
Plot's [band mark](https://observablehq.com/plot/marks/band).

### 7b. Shaded confidence bands vs discrete scenarios

- **Continuous bands** imply "we modeled this as a distribution." Use when you
  actually did.
- **Discrete scenarios** — three labeled lines (Conservative / Base / High
  growth) — are honest when the different lines come from different
  *assumptions* (pricing changes, onboarding 3 vs 10 customers). Label each
  line clearly.

### 7c. "Days until budget exhaust" callout

Not a chart, but a critical FinOps primitive. Plot a running cumulative-
spend line against the month's budget line, extend at the current burn rate,
and pin a label at the intersection: "budget exhausted on Mar 22 at
current rate."

```
$budget  ───────────────────────────
                               ╱
                              ╱ ← projected
                           ╱ │
         actual ─────────  │ │
                           │ │
                          Mar 19  Mar 22 ← BUDGET EXHAUST
```

**Implementation.** Recharts `<ReferenceLine>` at budget, `<ReferenceDot>`
at the intersection, `<Label>` with the date. Compute intersection in JS.

**Common mistakes.**
- Extrapolating a noisy daily series linearly. Use a rolling-7d smoothed burn
  rate.
- Not labeling the forecast start. The reader needs a vertical line saying
  "future starts here."

---

## 8. Token tier — AI-cost-specific

AI cost has a kind of structure that's unlike warehouse or egress cost:
token flows partition into discrete tiers, each priced differently. Making
these tiers visible is the single highest-ROI AI cost viz pattern.

### 8a. Stacked bar of tier composition

```
per model, per day:
  cache-read (cheap)      ▓▓▓▓▓▓▓▓▓▓▓
  cache-write 5m          ▒▒
  cache-write 1h          ░
  uncached-input          ████
  output                  ██
```

**When to use.** *Always*, for any Anthropic/OpenAI spend breakdown. Stacking
tiers makes visible the shift from "mostly uncached" to "mostly cache-read"
that is the goal of any prompt-caching optimization. It also reveals cache
thrash (lots of cache-writes relative to cache-reads) which is a failure mode.

**Implementation.** Stacked bar per day; use a sequential ramp for the cache
tiers (darkest = uncached = most expensive) and a contrast color for output.
```tsx
<BarChart data={tokens}>
  <Bar dataKey="cache_read_1h"   stackId="t" fill={emerald[800]} />
  <Bar dataKey="cache_read_5m"   stackId="t" fill={emerald[600]} />
  <Bar dataKey="cache_write_1h"  stackId="t" fill={indigo[500]} />
  <Bar dataKey="cache_write_5m"  stackId="t" fill={indigo[300]} />
  <Bar dataKey="uncached_input"  stackId="t" fill={violet[500]} />
  <Bar dataKey="output"          stackId="t" fill={violet[900]} />
</BarChart>
```
Tier order (bottom → top): cheapest to most expensive. Reader sees the
expensive tiers "floating on top."

### 8b. Cache-hit-rate gauge + $ saved counter pair

Pair pattern:

```
┌────────────────────┐   ┌────────────────────┐
│   cache hit rate   │   │   saved this month │
│                    │   │                    │
│       73%          │   │      $4,280        │
│    ▓▓▓▓▓▓▓▓░░      │   │                    │
│    good ← → great  │   │   vs uncached runs │
└────────────────────┘   └────────────────────┘
```

The gauge gives a fast health read; the counter gives monetary motivation.
Combine with a sparkline of cache-hit-rate-over-time to show whether
caching is getting better or worse as prompts drift.

### 8c. Model-arbitrage comparison

Two-panel view: same x-axis (task difficulty bucket), y-axis cost per
completion, one series per model. Shows "Haiku is 3x cheaper than Sonnet
for tasks that don't need Sonnet-level reasoning."

Pair this with a quality-matched scatter (section 5c) — only models
*at the same quality level* can be fairly compared on cost.

```
$ per call
   │     Sonnet ●●
   │            ●●●
   │  Haiku ○○○○○○
   │        ○○○
   └──────────────────→ task difficulty bucket
```

**Common mistakes.**
- Mixing token cost with API-call count without normalizing. Report
  $/million-tokens or $/call explicitly.
- Not showing cache-write as a distinct tier — it's cheaper than uncached
  input but not free, and hiding it overstates caching ROI.

---

## 9. Map-style

### 9a. Hour-of-day × day-of-week heatmap

```
      0  3  6  9  12 15 18 21
Mon  [░  ░  ░  ▒  █  █  █  ▒]
Tue  [░  ░  ░  ▒  █  █  █  ▒]
Wed  [░  ░  ░  ▒  █  █  █  ▒]
Thu  [░  ░  ░  ▒  █  █  █  ▒]
Fri  [░  ░  ░  ▒  █  █  █  ░]
Sat  [░  ░  ░  ░  ░  ░  ░  ░]
Sun  [░  ░  ░  ░  ░  ░  ░  ░]
```

**When to use.** Diurnal + weekly usage patterns. Answers: when are our
warehouses actually under load? Can we auto-suspend more aggressively
overnight? Do weekends cost anything? This is one of the highest-ROI
optimization charts.

**When NOT to use.** When the underlying data is sparse (you'll see a mostly
empty grid). When you care about the total — pair with a per-hour line
summary.

**Implementation.** Plot one-liner:
```tsx
Plot.plot({
  color: { scheme: "blues", legend: true, label: "credits" },
  marks: [
    Plot.cell(usage, { x: "hour", y: "weekday", fill: "credits", inset: 0.5 }),
  ],
});
```
visx: `<HeatmapRect>`. Recharts has no native heatmap.

### 9b. Dependency graph / DAG with per-node cost

```
    ┌────────────┐
    │ seed_data  │ $0.10
    └─────┬──────┘
          │
    ┌─────▼──────┐         ┌──────────────┐
    │ stg_orders │ $2.10──▶│ stg_products │ $1.40
    └─────┬──────┘         └──────┬───────┘
          │                       │
          └──────────┐   ┌────────┘
                    │   │
                ┌───▼───▼────┐
                │ fct_orders │ $18.60  ◀──── expensive node!
                └────────────┘
```

**When to use.** dbt project viz. Node = model, edge = ref() dependency,
node size or color ∝ runtime cost. Same construction for Airflow DAGs,
Dagster assets. The expensive nodes pop visually, giving you a clear
list of "what to optimize first."

**Implementation.** [React Flow](https://reactflow.dev) is the best React-
native option — give it nodes with `style={{background: color(cost)}}`
and edges. [Elkjs](https://github.com/kieler/elkjs) or [dagre](
https://github.com/dagrejs/dagre) for auto-layout. Manta's dbt-osmosis and
Paradime do this very well.

Alternative (static): visx `@visx/network` for a force-directed or manually
laid-out graph. For drill-down into a single model's runs, fall back to
Pareto (section 4e) sorted by model.

**Common mistakes.**
- DAGs that don't lay out left-to-right (root → leaves). It's the only
  direction humans read comfortably.
- Edge color encoding that doesn't match node color. Keep edges neutral
  gray; use color only for nodes.
- No cost labels on nodes. Color is coarse; the actual $ number next to
  each expensive node is what gets action.

---

## 10. Palette / Color guidance

### 10a. Costly's current palette

The live palette lives in two places:

1. **Tailwind v4 OKLCH tokens** in
   `frontend-next/src/app/globals.css` — shadcn/ui defaults for
   `--chart-1` through `--chart-5`. Light mode uses warm reds/yellows
   (`oklch(0.646 0.222 41.116)` is a terracotta), dark mode uses the
   indigo/emerald/violet set we want.
2. **Hardcoded chart array** in
   `frontend-next/src/lib/constants.ts`:
   ```ts
   COLORS.chart = [
     "#0EA5E9",  // sky-500
     "#6366F1",  // indigo-500
     "#14B8A6",  // teal-500
     "#F59E0B",  // amber-500
     "#8B5CF6",  // violet-500
     "#EC4899",  // pink-500
     "#10B981",  // emerald-500
     "#F97316",  // orange-500
   ];
   ```

The `ChartPanel` component uses `COLORS.chart`, not the CSS tokens — so
the effective palette is the `constants.ts` one. The *intent* is sky-
indigo-teal-emerald with amber/violet for 5th and 6th series.

**Action item:** consolidate. Either (a) generate `COLORS.chart` from the
CSS tokens at runtime (`getComputedStyle(document.documentElement)
.getPropertyValue("--chart-1")`) so dark mode re-themes, or (b) drop the
CSS chart tokens and keep the hardcoded ones with a documented "Costly
chart palette."

### 10b. Encoding by role

| Role           | Idiom                                   | Example tokens                        |
|----------------|-----------------------------------------|----------------------------------------|
| Category       | Qualitative palette, max 8 hues         | `COLORS.chart`                         |
| Magnitude      | Sequential single-hue ramp              | indigo-100 → indigo-700                |
| Diverging      | Two-hue ramp around a neutral center    | red → white → green (bud. variance)    |
| Sentiment pos  | Green (#059669 emerald-600)             | savings, under-budget                  |
| Sentiment neg  | Red (#DC2626 red-600)                   | over-budget, anomaly spike             |
| Neutral        | Slate-500 (#64748b)                     | reference lines, axes, medians         |
| Forecast       | Dashed + lower opacity                  | P50 line, projection band              |

**Rule of thumb.** Red and green are *reserved* for sentiment (good/bad).
Don't use them as categorical colors for platform names — when AWS gets
the green slot and spend is over budget, the reader's eye fights itself.

### 10c. Colorblind-safe alternatives

~8% of men have red-green CVD (deuteranopia / protanopia); a few percent have tritanopia. Mitigations:

- Use **ColorBrewer "Dark2" / "Set2"** qualitative palettes up to 8 categories (CVD-tested) — https://colorbrewer2.org/#type=qualitative.
- Use **Viridis** / **Cividis** for sequential magnitude (perceptually uniform; Cividis has best CVD performance).
- Don't rely on color alone — dual-encode with shape, dash, or +/− text.
- Test with Color Oracle (https://colororacle.org) or Chrome DevTools → Rendering → Emulate vision deficiencies.

Drop-in CVD-safe variant for Costly's palette:
```ts
COLORS.chartCvd = [
  "#1b9e77",  // teal
  "#d95f02",  // orange
  "#7570b3",  // violet
  "#e7298a",  // magenta
  "#66a61e",  // green
  "#e6ab02",  // gold
  "#a6761d",  // brown
  "#666666",  // gray
];
```
(ColorBrewer Dark2.)

### 10d. WCAG contrast targets

- **Text on chart background**: 4.5:1 (WCAG AA body text) or 3:1 (AA large,
  ≥18px or ≥14px bold). Axis labels and tooltips fall under "text."
- **Non-text UI / graphical objects**: 3:1 contrast between adjacent colors
  that carry meaning (WCAG 2.1 SC 1.4.11,
  https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html). This
  applies to *boundaries* between chart segments — a pie slice needs 3:1
  contrast against adjacent slices, or a visible stroke.
- **Focus indicators** on interactive chart elements (hover, keyboard tab
  ring): 3:1 against their background.

Tools: [WebAIM contrast checker](https://webaim.org/resources/contrastchecker/),
[a11y.color](https://a11y.color/).

**Rule of thumb for light-mode charts on `oklch(1 0 0)` background:** all
chart tokens should have OKLCH lightness ≤ 0.7. Costly's current
`--chart-4: oklch(0.828 0.189 84.429)` (yellow-ish) is borderline — pale
yellows fail non-text contrast on white.

### 10e. Dark-mode note

Recharts `Tooltip` and `Legend` don't pick up CSS-variable backgrounds by
default. Override:
```tsx
<Tooltip
  contentStyle={{
    background: "var(--popover)",
    border: "1px solid var(--border)",
    color: "var(--popover-foreground)",
  }}
  cursor={{ fill: "var(--muted)" }}
/>
```

---

## Quick-pick matrix

| Question                                         | First choice         | Fallback                        |
|--------------------------------------------------|----------------------|----------------------------------|
| "How much did we spend over time?"               | Stacked area         | Line-per-platform + small mult.  |
| "Where is the money going *right now*?"          | Horizontal stacked bar| Donut + total-in-hole            |
| "Hierarchy: platform → service → resource"       | Treemap (visx)       | Sunburst for shallow trees       |
| "Which team is responsible?"                     | Sankey (visx)        | Alluvial for reassignment        |
| "What's a normal query cost?"                    | Histogram (log)      | Violin for bimodal               |
| "What's concentration?"                          | Pareto               | Lorenz + Gini for reporting      |
| "Is cost tracking with volume?"                  | Scatter + regression | Hexbin for >5k points            |
| "Are we over/under budget, by how much?"         | Deviation bars       | Bullet chart for single metric   |
| "How does the month project out?"                | Fan chart (P10/P50/P90)| Discrete scenarios             |
| "Is our caching working?"                        | Tier-stacked bar + gauge pair | —                       |
| "When are we actually running?"                  | Hour-of-day × DOW heatmap | —                           |
| "Which dbt model is expensive?"                  | Colored DAG (React Flow) | Pareto by model              |

---

## Recharts 3 cheat sheet

- `<Tooltip formatter>` is `(value, name, props) => node`; use the arrow-wrap pattern (`(v) => formatCurrency(Number(v))`) already used in `ChartPanel`.
- Stack order = child order. Sort `yKeys` by magnitude descending.
- Log-scale y-axis: `<YAxis scale="log" domain={["auto","auto"]} />`. Zeros break it — filter or clip to epsilon.
- Always wrap in `<ResponsiveContainer>`. Use `<ReferenceLine/Area/Dot>` for annotations.

When Recharts isn't enough (Sankey, calendar heatmap, hour-of-day heatmap, small-multiples faceting, violin, hexbin, DAG, chord, marimekko, sunburst): reach for **Observable Plot** (declarative one-liners), **visx** (full control, React-native SVG), or **Apache ECharts** via `echarts-for-react` (only when a specific chart is missing from both).

---

## Further reading

- Claus Wilke — https://clauswilke.com/dataviz (ch. 10 directory of viz; ch. 15–17 uncertainty, trends, geospatial)
- Cole Nussbaumer Knaflic — *Storytelling with Data* (decluttering)
- Stephen Few — bullet-graph spec, https://perceptualedge.com/articles/misc/Bullet_Graph_Design_Spec.pdf
- Tufte — slope-graph & small-multiples, https://www.edwardtufte.com/bboard/q-and-a
- Vantage *Cloud Cost Handbook* — https://handbook.vantage.sh
- CloudZero blog — https://www.cloudzero.com/blog
- Datadog cloud cost management — https://docs.datadoghq.com/cloud_cost_management/
- FinOps Foundation — https://www.finops.org/framework/
- Observable Plot / visx / Recharts / ECharts galleries (see top of doc)
