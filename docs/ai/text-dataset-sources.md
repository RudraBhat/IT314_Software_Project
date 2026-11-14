# Text dataset sources

Where to get **real** texts for the label schema in [text-label-guideline.md](text-label-guideline.md):
`cyclone`, `flood`, `fire`, `earthquake`, `other_disaster`, `not_disaster`, in `en`, `hi` and `gu`.

Researched 5 Nov 2026. Licences were read from dataset cards and mirrors, which sometimes disagree.
**Siddh confirms each licence from the file inside the download before the data is used.**

## Key findings

- **There is no labelled Gujarati disaster dataset.** Gujarati has to be built from unlabelled
  Gujarati text (news, official bulletins, alerts) that the team filters and labels.
- **Hindi has only earthquake tweets (FIRE 2017) and one multilingual Indian dataset (MMT).**
  Expect Hindi to be built mostly the same way as Gujarati.
- **English is well covered.** HumAID, Disaster Response Messages and the Kaggle disaster tweets
  already carry flood / fire / earthquake / storm style labels that map almost directly.
- **`fire` (industrial) is the weakest class.** Most public "fire" data is wildfire. Use the
  explosion and refinery events, the `keyword` column of the Kaggle set, and Indian factory-fire
  headlines (see the table).
- **Licences:** most crisis tweet sets are CC BY-NC(-SA) 4.0. That is fine for a non-commercial
  course project, but tweet text also falls under X's terms. **Do not commit tweet text to the repo.**
  Keep the raw downloads on the team Drive and commit only the loader script, tweet IDs and the
  final labels (or a de-identified, sampled CSV after Siddh's licence check).

## A. English — labelled crisis datasets

| # | Source | Size / content | Maps to our labels | Licence (verify) | Get it |
|---|---|---|---|---|---|
| A1 | **HumAID** (QCRI, 2021) | ~77k annotated tweets, 19 events 2016–19, incl. **2018 Kerala floods** (8,056) and Cyclone Idai. *Event-type* config: flood, fire, earthquake, hurricane | flood→`flood`, hurricane→`cyclone`, earthquake→`earthquake`, fire is wildfire → `other_disaster` (not `fire`); `not_humanitarian` is still on-topic, not `not_disaster` | CC BY-NC-SA 4.0 (card also says BY-NC) | [crisisnlp.qcri.org/humaid_dataset](https://crisisnlp.qcri.org/humaid_dataset), [HF: QCRI/HumAID-event-type](https://huggingface.co/datasets/QCRI/HumAID-event-type), [HF: QCRI/HumAID-all](https://huggingface.co/datasets/QCRI/HumAID-all) |
| A2 | **Disaster Response Messages** (Figure Eight / Appen) | 26k messages (train 21,046 / val 2,573 / test 2,629): Haiti & Chile earthquakes, 2010 Pakistan floods, Sandy, plus news. Has the **original-language text** too | Binary columns `floods`, `storm`, `fire`, `earthquake`, `other_weather`, `cold`; `related=0` → `not_disaster` | Unknown on card — check Appen terms | [HF: community-datasets/disaster_response_messages](https://huggingface.co/datasets/community-datasets/disaster_response_messages) |
| A3 | **Kaggle "NLP with Disaster Tweets"** | ~10k tweets, `target` 1/0 and a `keyword` column (e.g. *explosion*, *chemical emergency*, *flood*, *hurricane*, *earthquake*, *blaze*) | `target=0` → `not_disaster` (best source of hard negatives like "my mixtape is fire"); keyword → class | Competition rules (Figure Eight "Data for Everyone") | [kaggle.com/competitions/nlp-getting-started](https://www.kaggle.com/competitions/nlp-getting-started), [HF mirror](https://huggingface.co/datasets/gdwangh/kaggle-nlp-getting-start) |
| A4 | **CrisisLexT26** | 26 events 2012–13, ~1k labelled tweets each. Includes **West Texas fertiliser explosion, Venezuela refinery explosion, Brazil nightclub fire**, Alberta / Sardinia / Philippines / Manila floods, Typhoon Yolanda / Pablo | explosion & refinery → `fire`; floods → `flood`; typhoons → `cyclone`; "not related" → `not_disaster` | CrisisLex terms | [crisislex.chato.cl/data-collections.html](https://www.crisislex.chato.cl/data-collections.html) |
| A5 | **CrisisBench** (8 datasets merged) | 166k informativeness + 141k humanitarian tweets, 61 events, `lang` field (42 values) | Use the `event` name to assign the class; `not_informative` → candidate `not_disaster` (check by hand) | CC BY-NC-SA 4.0 | [crisisnlp.qcri.org/crisis_datasets_benchmarks](https://crisisnlp.qcri.org/crisis_datasets_benchmarks.html), [HF: QCRI/CrisisBench-all-lang](https://huggingface.co/datasets/QCRI/CrisisBench-all-lang) |
| A6 | **CrisisMMD** | 7 events in 2017 (hurricanes Harvey/Irma/Maria, Mexico & Iraq-Iran earthquakes, California wildfires, **Sri Lanka floods / Cyclone Mora**) | by event | CC BY-NC-SA 4.0 | [crisisnlp.qcri.org/crisismmd](https://crisisnlp.qcri.org/crisismmd), [HF: QCRI/CrisisMMD](https://huggingface.co/datasets/QCRI/CrisisMMD) |
| A7 | **TREC-IS** (2018–21) | 136k annotated tweets, 98 events: wildfire, earthquake, flood, typhoon/hurricane, bombing | by event type | TREC data agreement | [trec.nist.gov/data/incident.html](https://trec.nist.gov/data/incident.html), [Glasgow host](https://www.dcs.gla.ac.uk/~richardm/TREC_IS) |

Use A1–A3 first: they already carry class-like labels, so they need the least relabelling.

## B. Hindi and code-mixed

| # | Source | What | Use | Get it |
|---|---|---|---|---|
| B1 | **FIRE 2017 IRMiDis** | 66,921 tweets about the 2015 Nepal earthquake; **16,903 in Hindi, Nepali or code-mixed** | `earthquake` only (+ off-topic ones as `not_disaster`) | Overview: [CEUR Vol-2036 T2-1](https://ceur-ws.org/Vol-2036/T2-1.pdf); ask the organisers (IIEST Shibpur / IIT Kharagpur) for the data |
| B2 | **MMT** (IIT Gandhinagar, EACL 2023) | 1.75M Indian tweets, 47 languages; *Natural disaster* topic (cyclone, earthquake, flood) = 75,591 tweets, incl. Hindi | Filter by topic + `hi`, then label | Paper: [arXiv 2304.00634](https://arxiv.org/abs/2304.00634). Not openly hosted — email the authors (Dwip Dalal, Mayank Singh, IIT Gandhinagar) |
| B3 | **Disaster Response Messages** original-language column | Some non-English originals (Urdu listed) | Few rows, but real | as A2 |
| B4 | **PIB Hindi press releases** | Government releases incl. cyclone / flood / NDRF updates | Filter by keyword → label | [HF: ai4bharat/Pralekha](https://huggingface.co/datasets/ai4bharat/Pralekha), [HF: pib](https://huggingface.co/datasets/pib), [pib.gov.in](https://pib.gov.in) |
| B5 | **IndicCorp v2 (Hindi)** | Large Hindi news / web text | Keyword-filter for बाढ़, चक्रवात, भूकंप, आग, विस्फोट, गैस रिसाव, लू; also random sentences as `not_disaster` | CC0 per README — [HF: ai4bharat/IndicCorpV2](https://huggingface.co/datasets/ai4bharat/IndicCorpV2) |

## C. Gujarati (no labelled set exists — build it)

| # | Source | What | Use |
|---|---|---|---|
| C1 | **Our own SACHET ingestion** | `external_alerts` rows from the SACHET CAP adapter (S2-09). CAP alerts are issued in several languages, Gujarati and Hindi among them | Real official cyclone / flood / heatwave text for Gujarat. Export `raw_payload` (the CAP headline / description) with `language` and `event_type` from the staging DB, rows with `is_fallback = false` only; keep running the adapter to grow the set. `event_id` = `source_uid` |
| C2 | **IndicCorp v2 (Gujarati)** | Large Gujarati news / web corpus, `data/gu.txt` | Keyword-filter: પૂર, વરસાદ, વાવાઝોડું, ચક્રવાત, ભૂકંપ, આગ, વિસ્ફોટ, ગેસ લીક, GIDC, હીટવેવ / લૂ. Random lines → `not_disaster`. CC0 per README — [HF](https://huggingface.co/datasets/ai4bharat/IndicCorpV2), [AIKosh](https://aikosh.indiaai.gov.in/home/datasets/details/ai4bharat_indiccorp_v2.html) |
| C3 | **L3Cube-IndicNews (Gujarati)** | 33k ABP Asmita headlines and articles, 10 topics (no disaster topic) | Filter the *State* / *Nation* topics by keyword → label. Other topics are clean `not_disaster` — [arXiv 2401.02254](https://arxiv.org/abs/2401.02254) |
| C4 | **iNLTK Gujarati headlines** | ~31k headlines (entertainment, business, tech) | `not_disaster` negatives — [github.com/goru001/nlp-for-gujarati](https://github.com/goru001/nlp-for-gujarati) |
| C5 | **Gujarati News Article Text Dataset** | General Gujarati news | Keyword filter — [Mendeley 76m24zdxcb](https://data.mendeley.com/datasets/76m24zdxcb/1) |
| C6 | **PIB Gujarati releases** | Gujarati government releases | Filter for cyclone / flood updates — [HF: ai4bharat/Pralekha](https://huggingface.co/datasets/ai4bharat/Pralekha) |
| C7 | **Official Gujarat bulletins** | GSDMA, IMD Ahmedabad Meteorological Centre, Gujarat Information Department press notes (Biparjoy 2023, Tauktae 2021, monsoon floods) | Hand-copy short sentences with the URL in `source`; government text, but record the URL so Siddh can check the terms |

## D. Indian English news (Gujarat events, industrial fire)

| # | Source | What | Use |
|---|---|---|---|
| D1 | **Times of India headlines** (2001–2023) | ~3.8M headlines with dates | Filter `gujarat|ahmedabad|surat|vadodara|kutch|bharuch|dahej|GIDC` × disaster keywords. Gives real Gujarat **cyclone, flood and factory-fire / blast / gas-leak** headlines, each with a date for `event_id`. CC0 on Harvard Dataverse ("Times of India News Headlines") and [HF](https://huggingface.co/datasets/times_of_india_news_headlines); Kaggle copy by Rohit Kulkarni (check its licence separately) |
| D2 | **GDELT** | Global news event index with source URLs | Pull URLs for Indian industrial-accident events, then copy headlines only — [gdeltproject.org](https://www.gdeltproject.org) |

## E. Augmentation (train split only)

- **Translate English crisis texts into Hindi and Gujarati** with AI4Bharat
  [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2) (MIT). Mark `synthetic=true`,
  `source=indictrans2:<original source>`; keep the original's `event_id` so the translation and the
  original land in the same split. Never put translations in test.
- LLM-written texts stay the last resort, as the guideline already says.

## Suggested collection plan to reach the dataset target

Target: ≥ 600 items, ≥ 20 per class in test, test human-written only.

| Class | Main sources | Gujarat / Indian test material |
|---|---|---|
| `cyclone` | A1 (hurricane), A4 (typhoons), C1 | C1 SACHET, C7 Biparjoy / Tauktae bulletins, D1 headlines |
| `flood` | A1 (Kerala floods), A2 `floods`, A4 | C1, C2 / C3 filtered, D1 headlines |
| `fire` | A3 keywords *explosion / chemical emergency / blaze*, A4 West Texas + Venezuela refinery | D1 GIDC / Dahej / Bharuch fire and blast headlines, C2 filtered |
| `earthquake` | A1, A2, B1 (Hindi) | C2 filtered (Kutch / Bhuj), D1 |
| `other_disaster` | A1 wildfire, A2 `other_weather` / `cold` | C1 heatwave / heavy-rain alerts, C2 લૂ / હીટવેવ |
| `not_disaster` | A3 `target=0`, A2 `related=0` | C3 / C4 non-news topics, B5 / C2 random lines |

Rules when importing:

1. Sample per source (for example 40–60 per class from A1–A4); don't import whole datasets.
2. Relabel every imported item with our guideline. Their labels are only hints.
3. `source` = dataset name + original ID; `event_id` = original event name (or date + place for
   headlines), so `validate_dataset.py` keeps events out of both train and test.
4. Strip names, phone numbers, @handles and exact addresses before saving.
5. Build the **test split from Indian / Gujarat material** (C1, C7, D1 and real Hindi / Gujarati
   texts) so the scores reflect the demo setting.
