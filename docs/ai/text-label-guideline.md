# Text dataset: label schema and guideline (S1-10)

One page for everyone who labels texts. The text model is **advisory only**; a dispatcher decides.

## Label schema (exactly one label per text)

| label | use when the text is about | maps to scenario |
|---|---|---|
| `cyclone` | cyclone, storm surge, strong wind damage on the coast | `CYCLONE` |
| `flood` | flooding, waterlogging, overflowing river or drain | `URBAN_FLOODING` |
| `fire` | fire, blast, gas or chemical leak at a factory or plant | `INDUSTRIAL_FIRE` |
| `earthquake` | ground shaking, building cracks or collapse from a quake | none (not supported yet) |
| `other_disaster` | a real disaster that is not one of the four above (landslide, heatwave, drought) | none |
| `not_disaster` | opinion, news commentary, jokes, ads, everyday talk | none |

## Rules for edge cases

- A **heatwave** or **landslide** is `other_disaster`, not `not_disaster`.
- An **opinion** about a disaster ("the government is useless after the flood") is `not_disaster`.
- Past events in a history article are `not_disaster`; a live report ("water is entering homes now") gets the disaster label.
- Two disasters in one text: choose the one that needs a response first and note it in `notes`.
- If you cannot decide in 20 seconds, set `label` to `UNCLEAR` and say why in `notes`. Neeti resolves these before validation.

## Gujarat examples

| text | label |
|---|---|
| Ahmedabad: Sabarmati ka pani Vasna barrage ke paas ghar me ghus gaya hai | `flood` |
| Dahej GIDC plant ma gas leak, kaamdaro bahar nikli gaya | `fire` |
| Gir Somnath coast par tez pavan ane vruksho ukhdi gaya, cyclone no asar | `cyclone` |
| Kutch ma dharti dhruji, ek dival ma tirad padi | `earthquake` |
| Saurashtra ma garmi 46 degree, heatwave ni chetavni | `other_disaster` |
| Barish pe sirf memes bana rahe ho, kuch kaam karo | `not_disaster` |

## Spreadsheet columns (`ai-workers/data/text_dataset_template.csv`)

`text,label,lang,source,synthetic,event_id,notes`

- `lang`: `en`, `hi` or `gu` (Hinglish and Gujarati written in Latin script count as `hi` or `gu`).
- `source`: where the text came from (a URL, an advisory name, `team-written` or `llm-synthetic`). Never blank.
- `synthetic`: `true` for LLM-generated or invented texts, otherwise `false`.
- `event_id`: one id per real event or per writing template. Texts sharing an `event_id` always land in the same split.
- Remove names, phone numbers and exact addresses before saving.

## Where texts come from

1. Public headlines and official advisories (record the source URL; Siddh checks the licence).
2. Citizen-style posts from the source spiked in S1-15 (public posts only).
3. Posts written by the team (`team-written`).
4. Only if labelling falls short: LLM synthetic texts, `synthetic=true`, training split only.

## Splits

- Test is human-written only (`synthetic=false`) and split by `event_id`, so test never shares an event or template with train.
- Validation and train take the remaining events. Synthetic rows go to train only.
- The split is a hash of `event_id` (`assign_split` in `ai-workers/data/validate_dataset.py`), so it is reproducible.

## Labelling batches

Dhruvil, Rudra and Neeti each label about 200 texts, including the **same 60 shared texts**. Agreement on those 60 is reported as Cohen's kappa:

```bash
cd ai-workers && python eval/agreement.py neeti.csv dhruvil.csv rudra.csv
```

## Validate and run baselines

```bash
cd ai-workers
python data/validate_dataset.py data/text_dataset.csv
python eval/baselines.py data/text_dataset.csv --split val
```

## Done when

At least 600 labelled items, at least 20 per class in test, agreement on the 60 shared items reported, and no leakage.
