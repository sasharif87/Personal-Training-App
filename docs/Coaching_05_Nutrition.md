# AI Coaching System — Nutrition

**Daily Nutrition · Meal Planning · Meal Prep · In-Session Fueling · Product Library · Race Day**

---

## Overview

Nutrition is modeled across three distinct time scales, each with different goals and different system involvement:

| Scale | Scope | System Role |
|---|---|---|
| **Daily / weekly** | Food quality, macros, energy availability, recovery | Weekly meal plan generation; meal prep suggestions; shopping list |
| **In-session** | Fueling during training — carbs, fluid, electrolytes | Session-specific fueling targets; product selection from personal library |
| **Race day** | Carb loading, race morning, on-course execution | Race-specific fueling plan generated during taper week |

These are not separate concerns — they are connected. A poorly fueled training week suppresses adaptation. A poorly fueled long ride produces a false fitness signal. A well-executed race-day fueling plan only works if I have trained their gut to absorb those carb rates during the preceding build.

---

## Daily & Weekly Nutrition

### Nutrition Periodisation — Fueling to the Training Load

Nutrition targets are not static. Carbohydrate needs rise on hard training days and fall on easy or rest days. The system generates a weekly nutrition structure anchored to the training plan, not a fixed daily target.

| Day Type | Carb Target | Protein Target | Fat | Notes |
|---|---|---|---|---|
| Key session day (threshold/VO2) | High — 6–8g/kg | 1.6–2.0g/kg | Moderate | Prioritise pre-session carbs; top up post-session immediately |
| Long session day (> 90min) | High — 7–10g/kg | 1.6–2.0g/kg | Moderate | High carb throughout day; gut training consideration |
| Easy / Z2 day | Moderate — 4–5g/kg | 1.6–2.0g/kg | Higher | Can train fat oxidation if not doing fueled long runs |
| Rest day | Low–moderate — 3–4g/kg | 1.8–2.2g/kg | Higher | Still need protein for muscle repair; lower total calories ok |
| Race week (A-race) | Progressive carb loading | 1.6g/kg | Lower | Format-dependent loading protocol — see Race Day section |
| Post-NFOR / recovery week | Moderate + emphasis on micronutrients | 2.0–2.2g/kg | Moderate | Immune support; anti-inflammatory foods emphasised |

Protein targets are consistent across all day types — muscle protein synthesis does not take days off.

### Energy Availability

Energy availability (EA) = caloric intake − exercise energy expenditure, relative to lean body mass. Chronic low energy availability (LEA) is one of the most common and most underrecognised causes of poor adaptation, suppressed HRV, hormonal disruption, illness susceptibility, and stress fracture risk in endurance athletes.

The system tracks estimated EA from caloric expenditure (TSS-based) and estimated intake (from meal logs where entered). When EA appears chronically low — less than ~30 kcal/kg lean mass for more than 2 weeks — this is flagged explicitly, not buried in a note.

**LEA signals the system watches for:**
- Suppressed HRV without corresponding training load
- Performance plateau despite consistent training
- Repeated illness or slow recovery from illness
- Stress fracture history (flagged in injury log)
- Mood / motivation consistently low in post-session log

---

## Weekly Meal Planning

### How It Works

The system generates a weekly meal structure each Monday as part of the weekly review output. It is not a rigid prescription — it is a framework: which days need high-carb fueling, which recovery meals matter most, what to prep in advance to reduce friction.

The LLM receives: training plan for the week (session types, durations, intensities), athlete food preferences (stored in profile), any dietary restrictions, and previous week's nutrition compliance if logged. It outputs a structured weekly plan with daily structure and meal prep suggestions.

### Athlete Nutrition Profile

Stored in the Athlete Profile alongside physiological parameters:

```
Nutrition Profile
├── Dietary approach (omnivore | vegetarian | vegan | plant-forward | no restrictions)
├── Allergies / intolerances (gluten, lactose, nuts, etc.)
├── Dislikes (free text — "no fish", "no mushrooms")
├── Strong preferences (free text — "loves Thai food", "quick breakfast preferred")
├── Cooking time available
│   ├── Weeknight: low / moderate / high
│   └── Weekend: low / moderate / high
├── Household size (affects portion sizing)
├── Budget sensitivity (standard / cost-conscious)
└── Supplement use (creatine, caffeine, iron, vitamin D, etc.)
```

### Weekly Plan Structure

```
Monday  — Rest day
  Breakfast: overnight oats with banana and honey
  Lunch:     chicken and rice bowl with roasted veg
  Dinner:    salmon, sweet potato, green beans
  Snack:     Greek yoghurt + fruit
  Notes:     recovery focus — anti-inflammatory fats, moderate carb

Tuesday — Threshold bike (75min, TSS 78)
  Pre-session (90min before): oatmeal + banana + coffee
  Post-session (within 30min): rice cakes + protein shake OR chocolate milk
  Breakfast/lunch: high-carb day — pasta, rice, bread fine
  Dinner: well-rounded — lean protein + complex carbs + veg
  Notes: High carb day. Don't skip the post-session window.

Wednesday — Easy run (45min, TSS 32)
  Normal eating — moderate carbs ok
  Can go lower-carb at dinner if preferred (fat adaptation day)

...
```

### Meal Prep Recommendations

The system identifies which meals benefit most from advance prep given the week's schedule, and suggests a prep session (typically Sunday or Monday evening):

```
This week's meal prep suggestions:
─────────────────────────────────
Prep Sunday evening (45 min):
  □ Cook a batch of rice (serves 3 days of lunches)
  □ Roast a tray of veg — mix of sweet potato, peppers, courgette
  □ Marinate chicken breasts × 4 (ready for Mon/Tue dinners)
  □ Portion pre-session snacks for Tue/Thu: banana + rice cake bags

Quick prep Tuesday after session (10 min):
  □ Blend post-session shake — have ingredients ready in fridge
  □ Make overnight oats for Wednesday (2 min)

Saturday long ride day:
  □ Prep bottles and on-bike nutrition the night before
  □ Have post-ride meal ingredients pre-staged — cook within 30min of finishing
```

### Shopping List Generation

From the weekly meal plan, the system generates a consolidated shopping list grouped by supermarket section. Quantities adjusted for household size from the my profile.

```
Shopping List — Week of 10 June
─────────────────────────────────
Produce
  □ Bananas × 6
  □ Sweet potatoes × 4 (large)
  □ Bell peppers × 3
  □ Courgette × 2
  □ Spinach (1 bag)
  □ Broccoli × 1 head
  □ Lemons × 2

Protein
  □ Chicken breasts × 6
  □ Salmon fillets × 2
  □ Eggs × 12
  □ Greek yoghurt (large tub)

Carbs / Pantry
  □ Jasmine rice (1kg)
  □ Oats (if low)
  □ Pasta (if low)
  □ Rice cakes (1 pack)

Dairy / Fridge
  □ Milk
  □ Protein powder (check stock)
```

### Nutrition Compliance Logging

After meals I can optionally log in the UI — a simple high/moderate/low carb day rating, not calorie counting. This is low-friction and optional. Where logged, it feeds a compliance score into the weekly summary and allows the system to correlate nutrition compliance with execution quality over time.

---

## In-Session Fueling

### Session Fueling Targets

For every session over 90 minutes, the system generates a structured fueling plan — not just a note saying "eat something."

| Session Duration | Carb Target | Fluid Target | Sodium | Notes |
|---|---|---|---|---|
| < 60 min | 0–20g | 500ml | Minimal | Pre-load sufficient |
| 60–90 min | 30–40g/hr | 500–750ml/hr | Light | Optional; beneficial at high intensity |
| 90–180 min | 60–80g/hr | 750ml–1L/hr | 300–500mg/hr | Required; dual-source carbs strongly recommended |
| > 180 min | 80–100g/hr | 750ml–1L/hr | 500–1000mg/hr | Train-the-gut target for IM athletes |
| Race — Olympic | 40–60g/hr | By thirst | Electrolyte drink on bike | Short duration; mainly bike segment |
| Race — 70.3 | 70–80g/hr | 750ml/hr | 500mg/hr | Practised in training |
| Race — Ironman | 80–100g/hr | By thirst + conditions | 800–1200mg/hr | Non-negotiable — rehearsed in training |

### Dual-Source Carbohydrates

For sessions and races where carb intake exceeds ~60g/hr, dual-source carbohydrates (glucose + fructose, ideally 2:1 ratio) are required. Single-source glucose absorption is capped at ~60g/hr by intestinal glucose transporters. Adding fructose uses a separate transporter pathway and allows total absorption of 80–100g/hr. This is not optional for Ironman athletes — it is the mechanism that makes race-day fueling targets achievable.

Products that provide dual-source carbs: Maurten (40:27 glucose:fructose), SiS Beta Fuel (80g/serving, 1:0.8 ratio), Science in Sport Go Isotonic (22g/gel), most carb drinks designed for endurance. Pure glucose gels (many traditional gels) do not provide this benefit at high doses.

---

## Nutrition Product Library

This is one of the most practically useful features for me — it stores every product I use. The library stores every nutrition product I use, with exact macros, serving sizes, and personal tolerance history. The in-session fueling plan references the library by name, not just grams of carbohydrate.

### Product Entry Schema

```
Nutrition Product
├── product_id (uuid)
├── name               "Maurten Gel 100"
├── brand              "Maurten"
├── category           gel | drink | bar | chew | real_food | electrolyte | caffeine
├── serving_size_g     40
├── carbs_g            25         ← per serving
├── glucose_g          16         ← where known
├── fructose_g          9         ← where known
├── protein_g           0
├── fat_g               0
├── sodium_mg          50
├── caffeine_mg         0         ← 0 for non-caffeinated version
├── calories           100
├── format             gel | liquid | solid | semi-solid
├── portability        high | medium | low     ← fit in jersey pocket?
├── requires_water     false      ← isotonic gels don't; some do
├── personal_tolerance good | ok | poor | untested
├── gi_notes           "fine at 2/hr; problems at 3/hr on hot days"
├── use_contexts       [bike, run]   ← athlete finds it works for these sports
└── notes              "prefer caffeinated version after 2hrs"
```

### Built-In Product Library

A starter library of common products is included. Athletes add their own or edit entries with personal notes.

| Product | Category | Carbs/serving | Dual-Source | Caffeine |
|---|---|---|---|---|
| Maurten Gel 100 | Gel | 25g | ✓ | No |
| Maurten Gel 100 CAF 100 | Gel | 25g | ✓ | 100mg |
| Maurten Drink Mix 160 | Drink | 40g/500ml | ✓ | No |
| Maurten Drink Mix 320 | Drink | 80g/500ml | ✓ | No |
| SiS Beta Fuel Gel | Gel | 40g | ✓ (1:0.8) | Optional |
| SiS GO Isotonic Gel | Gel | 22g | Partial | Optional |
| Clif Shot Gel | Gel | 24g | No | Optional |
| Clif Bar | Bar | 42g | No | No |
| Science in Sport Rego | Recovery drink | 23g carbs + 23g protein | No | No |
| Precision Hydration PH1500 | Electrolyte | 0g carbs | — | No |
| Banana (medium) | Real food | 25g | Partial | No |
| Medjool dates × 2 | Real food | 36g | Partial | No |
| Rice cake (homemade) | Real food | 30g | Partial | No |

### In-Session Product Plan

For sessions over 90 minutes, the fueling plan is expressed in specific products from my product library, not just abstract grams:

```
Saturday Long Ride — 3hr 30min — Target: 80g carbs/hr

Pre-ride (20min before):
  1 × Maurten Gel 100 (25g carbs)

On bike — every 20 minutes:
  Hr 0–1:  2 × Maurten Drink Mix 160 bottle (40g each, 80g/hr) sip continuously
  Hr 1–2:  same + 1 × Maurten Gel 100 at 90min mark if needed (target 80g/hr)
  Hr 2–3:  switch to Maurten Drink Mix 320 bottle (80g/500ml) + 1 × Maurten Gel CAF 100 at 2hr30
  Final 30min: 1 × gel if stomach good; water only if feeling full

Fluid target: 750ml/hr — adjust by conditions (today: 22°C, moderate — 750ml is right)
Sodium: 400mg/hr — PH500 tab in each bottle

Total carbs: ~280g over 3.5hr ≈ 80g/hr ✓
Total caffeine: 100mg at 2hr30 — timed for final push
```

### Personal Tolerance Tracking

After every long session the post-session log includes:

```
In-session nutrition log
  What did you take? (checkboxes from product library + amount)
  Any GI issues? (none / mild / moderate / significant)
  Notes: (free text)
```

Over time the system builds a personal tolerance profile: which products cause issues at which doses, whether heat correlates with GI problems, whether running vs cycling affects tolerance. This informs future fueling recommendations — if Maurten gels are logged as "GI issues on hot runs" in three separate sessions, they are deprioritised for run segments in hot conditions.

---

## Gut Training

For IM and 70.3 athletes, the ability to absorb 80–100g carbs/hr on race day is a trainable adaptation. The intestinal mucosa upregulates glucose and fructose transporters in response to regular high-carb fueling during training. This takes 4–6 weeks of consistent practice.

### Gut Training Protocol

The system schedules explicit gut training sessions within the build — not a separate programme, but a progressive carb target escalation applied to existing long sessions:

| Build Week | Gut Training Target | Approach |
|---|---|---|
| Week 1–2 | 40–50g/hr | Establish the habit; no GI stress expected |
| Week 3–4 | 55–65g/hr | Mild adaptation demand; dual-source products only |
| Week 5–6 | 70–80g/hr | Primary adaptation window; any GI discomfort is adaptation |
| Week 7–8 | 80–90g/hr | Race-simulation target; product selection finalised |
| Race week | Practice product only — no new products | Execute the known plan |

### Gut Training Logging

After each gut training session I log: actual intake, GI response, conditions. The system tracks the escalation and adjusts if repeated GI issues occur — it may slow the progression rather than push through a problematic target. My personal data determines when the target is achievable, not the generic protocol.

---

## Race Day Fueling Plans

Race-day fueling plans are generated during taper week as part of A-race preparation. They are specific — product by product, kilometre by kilometre — not generic advice.

### Pre-Race Protocol

| Format | Carb Loading | Race Morning | Notes |
|---|---|---|---|
| Olympic / Sprint | No loading needed | 100–150g carbs, 2–3hr before | Standard pre-race meal; not a big change from normal |
| 70.3 | 1-day moderate loading | 150–200g carbs, 2–3hr before | Familiar foods only; proven race morning routine |
| Ironman | 3-day progressive loading | 200–250g carbs, 3hr before + gel 30min before | Day before: 10g/kg carbs; avoid excess fibre |
| Marathon | 2-day loading | 150–200g carbs, 2–3hr before | Rice, pasta, banana — no new foods |

### On-Course Plan

The on-course plan accounts for: race distance and expected duration, personal product library, aid station positions (for events where I rely on course nutrition), my trained gut capacity, and any heat or altitude adjustments.

```
A-Race Fueling Plan — Boulder 70.3 — 15 June 2027
────────────────────────────────────────────────────
Race morning
  5:30am: 180g oats + banana + honey + 500ml water
  6:45am: 500ml sports drink (Maurten 160)
  7:15am (30min before): 1 × Maurten Gel 100

SWIM (28min estimated)
  No nutrition — hydrate pre-race

T1
  1 × Maurten Gel 100 (eat in transition or first 5min of bike)

BIKE (2hr 25min estimated — target 78g/hr)
  Bottles: 2 × Maurten 320 (80g each) — consume bottle 1 by 45km, bottle 2 by 80km
  Gels: 1 × Maurten Gel 100 at 30km, 1 × Maurten Gel CAF 100 at 60km
  Sip every 10-15min — don't wait until thirsty

T2
  1 × gel if stomach ok; water only if not

RUN (1hr 35min estimated — target 60g/hr)
  Aid stations at ~2km intervals — take water at each
  Gels: 1 × SiS Beta Fuel at 5km, 1 × SiS Beta Fuel at 10km
  Caffeinated gel (Maurten CAF 100) at 15km if needed
  Avoid course gels unless pre-tested

Total on-course carbs: ~340g over 4hrs ≈ 78g/hr ✓
Total caffeine: 200mg (at 60km bike, 15km run)
────────────────────────────────────────────────────
Contingency: if stomach goes wrong on bike — switch to water only, stop gels,
try 1 Precision Hydration SOS tab per bottle. Resume gels at T2 if settled.
```

### Race Nutrition Review

After the race, the nutrition section of the race result intake captures: what was actually taken vs planned, any GI issues, timing deviations. This feeds the gut training and product tolerance model — a failed fueling plan is as informative as a successful one.

---

## Caloric Expenditure Modeling

Gross caloric expenditure estimated from TSS, FTP, and sport-specific efficiency factors:

| Sport | Efficiency Factor | Note |
|---|---|---|
| Cycling | ~0.235 | Mechanically efficient |
| Running | ~0.42 | Higher metabolic cost per unit effort |
| Swimming | ~0.38 | High — water resistance, whole-body effort |
| Strength | ~0.30 | Rough estimate — high variability |
| Climbing | ~0.38 | Similar to running due to vertical loading |

`Calories ≈ (TSS/100) × FTP × 3600 × efficiency_factor / 4184 × 1000 kcal`

This is an estimate, not a prescription. It feeds: weekly energy availability monitoring, post-session recovery meal sizing, and long-session fueling target calculations. It is not displayed as a calorie counting target — the system uses it to flag under-fueling patterns, not to create caloric restriction.

---

## Recovery Nutrition

The post-session window matters most for sessions above Z2 intensity or longer than 90 minutes. The system includes recovery meal guidance in session notes for qualifying sessions:

**The recovery window: 30–60 minutes post-session**

Target: 0.8–1.2g/kg carbohydrate + 20–30g protein within 30 minutes of finishing.

Simple options the system draws from based on athlete preferences and what is available:
- Chocolate milk (classic — fast, palatable, proven)
- Greek yoghurt + banana + honey
- Rice cakes + scrambled eggs (2 eggs)
- Protein shake + banana
- Smoothie: milk + banana + oats + protein powder

For sessions under 60 minutes or Z1/Z2 only: normal meal timing is fine — no urgent recovery window needed.

---

*AI Coaching System — Nutrition · March 2026 *
