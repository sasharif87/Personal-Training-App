**AI Coaching System**

Code Ideas & Technical Scratchpad

Libraries  •  Data Formats  •  Patterns  •  Implementation Notes

  This is a living scratchpad — ideas and patterns to pick up when coding starts. Not prescriptive. Expect to revise as implementation reveals better approaches.

# **Data Ingestion**

## **Garmindb**

Primary ingestion library. Pulls from Garmin Connect into local SQLite or MySQL. Handles FIT file parsing, activity types, HRV data, sleep, body battery.

pip install garmindb

python \-m garmindb.garmin\_db \--all \--latest   \# ongoing sync

python \-m garmindb.garmin\_db \--all            \# full historical pull

* Activities land in activities table with sport type, duration, distance, HR stats

* HRV and sleep in separate tables — join on date for daily readiness context

* FTP stored in user\_profile table — pull directly rather than calculating

* Planned workout definitions in separate table from completed activities — need both

## **Trainer Road Export**

Community tool — not officially supported but stable. Pulls full workout library and calendar history.

pip install trainerroad-export

trainerroad-export \--username X \--password Y \--output ./tr\_workouts/

* Outputs workout JSON with name, description, interval structure, power targets

* Match to Garmin completed activities by date to build plan/actual pairs

* Store workout description text — the coaching intent is the valuable part

* One-time historical pull; ongoing bike data comes via Garmin sync

## **Garmin Connect API via garth**

For reading planned workouts and writing back generated sessions. garth handles OAuth token management.

pip install garth

import garth

garth.login('email', 'password')   \# stores token locally

garth.save('\~/.garth')

* garth.connectapi() gives access to all Connect API endpoints

* GET /workout-service/workouts — fetch planned workout definitions

* POST /workout-service/workouts — push generated workout to calendar

* Risk: unofficial API, has broken with Garmin auth changes — monitor

# **Analysis Layer — JupyterLab**

## **CTL/ATL/TSB Calculation**

Standard fitness/fatigue/form model. Calculate per-sport and combined. Libraries to consider:

pip install fitparse pandas numpy scipy

* pandas for time-series manipulation from InfluxDB queries

* CTL \= 42-day exponentially weighted average of daily TSS

* ATL \= 7-day exponentially weighted average of daily TSS

* TSB \= CTL \- ATL (positive \= fresh, negative \= fatigued)

* Implement per-sport (swim TSS, run TSS, bike TSS) and combined

## **CSS Extraction from Swim Data**

Critical Swim Speed is the swim equivalent of FTP. Derive from historical best efforts.

* CSS \= pace at which you can sustain effort for \~30-40min — analogous to lactate threshold

* Estimate from: best 400m pace and best 200m pace using the formula: CSS \= (400-200) / (T400-T200)

* Extract from Garmin swim data — filter for CSS test efforts or use race data

* Recalculate quarterly as fitness changes — store history

* Swim TSS equivalent: s-TSS using CSS as threshold reference

## **HRV Correlation Analysis**

The goal is to find the HRV signals that are predictive for you specifically — population averages are a starting point, not the answer.

* 7-day HRV trend is more predictive than single-day readings — calculate rolling mean and SD

* HRV4Training-style analysis: when HRV drops \>10% below rolling baseline, flag

* Correlate HRV trend to subsequent workout execution quality — define execution quality metric first

* scipy.stats for correlation analysis — look for Pearson r between HRV trend and TSS achieved vs planned

from scipy import stats

r, p \= stats.pearsonr(hrv\_trend\_7d, execution\_ratio)

## **Environmental Impact Modeling**

Normalise workout data for environmental conditions to separate fitness signal from environmental noise.

* Temperature correction for running: roughly 1-2% pace degradation per degree C above \~15C

* Wind correction for cycling: use power data not pace — power is environment-independent

* Pull weather data for workout location/time — Open-Meteo API is free and self-hostable

* Build personal temperature response curve from 10 years of data — yours will differ from population

pip install openmeteo-requests

# **LLM Interface**

## **Ollama Setup**

ollama pull llama3:70b-instruct-q4\_K\_M   \# recommended quantisation

ollama pull mistral:7b-instruct           \# faster, lower quality — Phase A testing

* llama3 70B Q4\_K\_M is the target model — better quality than Q4\_0 at similar size

* Start development with 13B or 7B — faster iteration, same prompt structure

* Switch to 70B for quality assessment — compare outputs before committing to RAG build

## **Structured JSON Output**

Prompt the model to return JSON from day one. Parse and validate before using. This is the most important discipline — structured output enables everything downstream.

system\_prompt \= """

You are a triathlon coach. Respond ONLY with valid JSON.

No preamble. No markdown. No explanation outside the JSON structure.

Output format: { "week": { "sessions": \[...\], "rationale": "..." } }

"""

* Define session schema early and stick to it: type, sport, duration\_min, intensity\_zone, sets\[\], rationale

* Validate JSON before downstream use — model will occasionally produce malformed output

* Log all LLM inputs and outputs — essential for debugging and eventually for the fine-tuning dataset

## **Context Assembly Pattern**

The input to the LLM each cycle needs to be structured and consistent. Build a context assembler that produces the same JSON shape each time regardless of which data is available.

context \= {

  "athlete": { "ftp": 280, "css": "1:38/100m", "lthr\_run": 162 },

  "current\_state": { "ctl": 68, "atl": 72, "tsb": \-4, "hrv\_trend": "suppressed" },

  "block": { "phase": "build", "week": 6, "weeks\_to\_race": 8, "race\_format": "olympic\_tri" },

  "yesterday": { "planned": {...}, "actual": {...}, "execution\_ratio": 0.94 },

  "retrieved\_history": \[ {...}, {...} \],   // from RAG layer in Phase D

  "race\_calendar": \[ { "date": "2027-06-15", "format": "olympic\_tri", "priority": "A" } \]

}

## **FTP Prediction Logic**

Build as a separate module that runs alongside main pipeline and appends a flag to the context.

* Track rolling 90-day power curve — store best efforts at 1min, 5min, 20min, 60min

* If 20min best effort improves \>3% above current FTP estimate — flag ramp test

* If no threshold session in 21+ days — flag potential decay, note estimate may be optimistic

* Compare against historical FTP movement patterns — when did FTP historically respond to this type of block?

* Surface as a single advisory string appended to context: ftp\_advisory: 'Power curve suggests...'

# **Output Generation**

## **Garmin Workout Push**

Convert LLM JSON output to Garmin workout payload format and push via garth.

def push\_to\_garmin(session\_json):

    payload \= convert\_to\_garmin\_format(session\_json)

    garth.connectapi(

        '/workout-service/workouts',

        method='POST',

        json=payload

    )

* Run sessions: map intensity zones to pace zones based on current threshold pace

* Swim sessions: map CSS-relative targets to Garmin pace zone definitions

* Strength sessions: Garmin supports custom workout steps with text descriptions

* Test end-to-end before deploying automation — verify sessions appear correctly on watch

## **Zwift .zwo File Generation**

Convert bike session JSON to Zwift workout XML. Power targets are FTP fractions.

def session\_to\_zwo(session, ftp):

    segments \= \[\]

    for step in session\["sets"\]:

        if step\["type"\] \== "interval":

            segments.append(f'\<IntervalsT Repeat="{step\["repeat"\]}"'

                f' OnDuration="{step\["on\_sec"\]}" OffDuration="{step\["off\_sec"\]}"'

                f' OnPower="{step\["on\_watts"\]/ftp:.2f}" OffPower="{step\["off\_watts"\]/ftp:.2f}"/\>'

        )

    return zwo\_template.format(segments=chr(10).join(segments))

* Drop .zwo to Zwift workouts folder via SMB share — path: \\\\zwift-machine\\Zwift\\Workouts\\\[user\_id\]\\

* Use Syncthing as fallback if SMB share is unreliable across network

* With Tailscale, Zwift machine is reachable regardless of which network it is on

# **RAG Layer — Phase D**

## **Vector Database Setup**

pip install chromadb   \# or qdrant-client for Qdrant

* Chroma: simpler setup, good for single-node, persists to disk — good starting point

* Qdrant: more scalable, better filtering, self-hosted Docker container — better long term

* Docker: docker run \-p 6333:6333 qdrant/qdrant

## **What to Embed**

Each embedding represents a training block snapshot — a moment in time with context and outcome.

* Training block summary: sport mix, weekly hours, intensity distribution, CTL at start/end

* Physiological state at block start: HRV trend, TSB, sleep quality, FTP

* Environmental context: average temperature, race target

* Outcome: CTL change, FTP change, race performance if applicable, execution ratio

from sentence\_transformers import SentenceTransformer

model \= SentenceTransformer('all-MiniLM-L6-v2')   \# lightweight, runs on CPU

embedding \= model.encode(block\_summary\_text)

## **Retrieval Query Pattern**

At each planning cycle, build a query from current state and retrieve the most similar historical blocks.

query \= f"""

Build block week 6, Olympic tri target, CTL 68 ATL 72, HRV suppressed,

temperature averaging 28C, 8 weeks to race

"""

results \= collection.query(query\_embeddings=\[model.encode(query)\], n\_results=3)

* Return top 3 similar historical blocks with their outcomes

* Inject as 'retrieved\_history' in LLM context — let the model reason about what worked

* The LLM sees: 'In similar conditions in 2024 week 8 of build, reducing run volume 20% and maintaining swim/bike produced X outcome'

# **Orchestration & Scheduling**

## **Daily Pipeline**

Run as a cron job or systemd timer on the server. Overnight execution means latency is irrelevant.

\# /etc/systemd/system/coaching-pipeline.timer

\[Timer\]

OnCalendar=\*-\*-\* 03:00:00   \# 3am daily

Persistent=true

* 3am run: Garmindb sync, analysis layer update, LLM generation, output push

* Log everything — LLM inputs, outputs, API responses, errors

* Alert on failure — a missed day is recoverable; a silent failure is not

* Store all LLM outputs with inputs — this builds the fine-tuning dataset automatically

## **Fine-Tuning Dataset Collection**

The fine-tuning dataset builds passively as the system runs. Every input/output pair where you actually executed the suggested workout and the system got feedback is a training example.

\# Log structure for each cycle

log\_entry \= {

    "timestamp": "...",

    "input\_context": {...},   // full context sent to LLM

    "llm\_output": {...},      // generated workouts

    "execution\_data": {...},  // actual workout data 24hrs later

    "execution\_ratio": 0.94  // how well plan was followed

}

* Store in structured format from day one — retrofitting is painful

* After 12-18 months of operation you have enough pairs to consider fine-tuning

* Plan/actual pairs where execution ratio \> 0.85 are clean training examples

* Pairs where plan was significantly modified (substitutions, cancellations) need annotation before use

AI Coaching System — Code Ideas & Scratchpad  •  March 2026  •  Back burner, Priority 5