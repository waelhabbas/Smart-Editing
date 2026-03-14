# Smart Editing - Project Conventions

## Overview
Automated video editing service for Al Jazeera English reporters. Processes reporter recordings with a unified CSV template to generate edit-ready FCP7 XML timelines with B-Roll overlays, Soundbite insertions, and shift-aware SRT subtitles.

## Architecture

### Backend (`backend/`)
- **Framework**: FastAPI with async endpoints
- **Entry point**: `run.py` → `backend.app:app`
- **Pattern**: Router → Service → Pipeline modules
- **Routers** (`routers/`): `explainer.py`, `templates.py`, `downloads.py`
- **Services** (`services/`): `explainer_service.py` extends `BaseService`
- **Pipeline** (`pipeline/`): Independent processing modules called by services
- **Utils** (`utils/`): Shared utilities (text normalize, timecode, file ops, spelling)

### Frontend (`frontend/`)
- **Vanilla HTML/CSS/JS** (no framework)
- **Pages**: `index.html` (landing), `explainer.html` (workflow)
- **CSS**: Modular files in `css/` (variables, base, layout, components, animations, themes)
- **JS**: ES modules in `js/` (explainer.js, i18n.js, strings.js)
- **i18n**: Arabic (default) + English, RTL/LTR switching via `data-i18n` attributes
- **Theming**: Dark (default) + light mode via CSS custom properties and `[data-theme]`

## Processing Pipeline

### Step 1: `POST /api/explainer/step1` (Video + CSV)
1. Parse CSV → 2. Extract audio → 3. Whisper transcription → 4. Gemini AI take selection → 5. Build timeline → 6. Remove silences → 7. Compute positions → 8. Generate base XML → 9. Save metadata

### Step 2: `POST /api/explainer/step2` (B-Roll/Soundbite/Transition files)
1. Load metadata → 2. B-Roll overlay (V2) → 3. Soundbite insert with shift (V3+A2) → 4. Scale keyframes → 5. Transition track (V4+A3) → 6. Logo (V5) → 7. Outro (V6+A4) → 8. SRT (last)

## Key Conventions

### SRT Generation (always last step)
- Presenter shots: Use **CSV text** (not Whisper) with Whisper timing
- Soundbite shots: Use Whisper transcription of soundbite audio
- Max **8 words per line**
- Apply **British English** spelling rules
- Apply **soundbite shift offsets** to all timings

### Track Layout
- V1/A1: Presenter (base timeline)
- V2: B-Roll overlay (video-only, no audio)
- V3/A2: Soundbite insert (video + audio, shifts timeline)
- V4/A3: Transition (alpha video + SFX audio, centered on cut points)
- V5: Logo bug (still image overlay, full duration)
- V6/A4: Outro (alpha video + audio, overlaps end of timeline)

### CSV Template Format
Columns: `shot_number, text, Type, File_name, cut-01/in, cut-01/out, cut-02/in, cut-02/out, cut-03/in, cut-03/out`
- Type: empty (presenter), `BRoll`, `soundbite`
- Cut timecodes: `M:SS` or `H:MM:SS`
- Max 3 cuts per shot

### Text Matching
- Arabic text: Normalize diacritics, alef variants, taa marbuta before comparison
- Uses `rapidfuzz` sliding window for fuzzy matching
- Confidence threshold: 55%

### Gemini AI
- Model: `gemini-2.5-flash`
- Bilingual prompts (auto-detect Arabic/English)
- Selects best take per shot (defaults to last take if equal quality)
- 2 retries on failure

## Commands
```bash
# Run server
python run.py

# Install dependencies
pip install -r backend/requirements.txt
```

## Environment Variables
- `GEMINI_API_KEY`: Google Gemini API key (or enter in UI)

## File Outputs
- `output/{job_id}_base.xml`: Base timeline (V1+A1)
- `output/{job_id}_final.xml`: Final timeline with all tracks
- `output/{job_id}_subtitles.srt`: Shift-aware subtitles
- `output/{job_id}_metadata.json`: Job state between steps
