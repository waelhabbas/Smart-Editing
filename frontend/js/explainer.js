/* Explainer workflow - handles Step 1 and Step 2 processing */

import { initI18n, setLang, getLang, t } from './i18n.js';

// ── State ──────────────────────────────────────────────────────────────
let videoFile = null;
let csvFile = null;
let mediaFiles = [];
let logoFile = null;
let outroFile = null;
let transitionFile = null;
let jobId = null;
let requiredFiles = [];

// ── DOM refs ───────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    // Upload zones
    videoZone:    $('#videoZone'),
    csvZone:      $('#csvZone'),
    mediaZone:    $('#mediaZone'),
    logoZone:          $('#logoZone'),
    outroZone:         $('#outroZone'),
    transitionZone:    $('#transitionZone'),
    videoInput:   $('#videoInput'),
    csvInput:     $('#csvInput'),
    mediaInput:   $('#mediaInput'),
    logoInput:         $('#logoInput'),
    outroInput:        $('#outroInput'),
    transitionInput:   $('#transitionInput'),
    videoFileName: $('#videoFileName'),
    csvFileName:  $('#csvFileName'),
    mediaFileNames: $('#mediaFileNames'),
    logoFileNames:      $('#logoFileNames'),
    outroFileNames:     $('#outroFileNames'),
    transitionFileNames: $('#transitionFileNames'),

    // Buttons
    step1Btn:  $('#step1Btn'),
    step2Btn:  $('#step2Btn'),
    retryBtn:  $('#retryBtn'),

    // Sliders
    silenceSlider: $('#silenceSlider'),
    paddingSlider: $('#paddingSlider'),
    silenceVal:    $('#silenceVal'),
    paddingVal:    $('#paddingVal'),

    // Settings
    apiKeyInput: $('#apiKeyInput'),
    langSelect:  $('#langSelect'),

    // Sections
    step1Section: $('#step1Section'),
    step2Section: $('#step2Section'),

    // States
    emptyState:      $('#emptyState'),
    processingState: $('#processingState'),
    processingState2: $('#processingState2'),
    resultsState:    $('#resultsState'),
    errorState:      $('#errorState'),

    // Processing steps
    processingSteps:  $('#processingSteps'),
    processingSteps2: $('#processingSteps2'),

    // Stats
    statScenes:   $('#statScenes'),
    statOriginal: $('#statOriginal'),
    statFinal:    $('#statFinal'),
    statSaved:    $('#statSaved'),

    // Tokens
    tokenInfo: $('#tokenInfo'),
    tokIn:     $('#tokIn'),
    tokOut:    $('#tokOut'),
    tokTotal:  $('#tokTotal'),

    // Table
    scenesBody: $('#scenesBody'),

    // Downloads
    downloadXml: $('#downloadXml'),
    downloadSrt: $('#downloadSrt'),

    // Warnings
    warningsBox: $('#warningsBox'),

    // Error
    errorMsg: $('#errorMsg'),
};

// ── Helpers ────────────────────────────────────────────────────────────
function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
}

function showSection(toShow) {
    [dom.emptyState, dom.processingState, dom.processingState2, dom.resultsState, dom.errorState]
        .forEach(el => el.classList.add('hidden'));
    if (toShow) toShow.classList.remove('hidden');
}

function setStep(container, stepName, state) {
    const el = container.querySelector(`[data-step="${stepName}"]`);
    if (!el) return;
    el.classList.remove('step--active', 'step--done');
    if (state === 'active') el.classList.add('step--active');
    if (state === 'done') el.classList.add('step--done');
}

function validateStep1() {
    dom.step1Btn.disabled = !(videoFile && csvFile);
}

function validateStep2() {
    dom.step2Btn.disabled = mediaFiles.length === 0;
}

// ── Upload zone wiring ─────────────────────────────────────────────────
function wireUpload(zone, input, onFile, multi = false) {
    // Click to upload
    zone.addEventListener('click', (e) => {
        if (e.target.closest('a')) return; // don't intercept links
        input.click();
    });

    input.addEventListener('change', () => {
        if (multi) {
            onFile([...input.files]);
        } else if (input.files[0]) {
            onFile(input.files[0]);
        }
    });

    // Drag events
    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (multi) {
            onFile([...e.dataTransfer.files]);
        } else if (e.dataTransfer.files[0]) {
            onFile(e.dataTransfer.files[0]);
        }
    });
}

// ── Init upload zones ──────────────────────────────────────────────────
wireUpload(dom.videoZone, dom.videoInput, (file) => {
    videoFile = file;
    dom.videoFileName.textContent = file.name;
    dom.videoZone.classList.add('has-file');
    validateStep1();
});

wireUpload(dom.csvZone, dom.csvInput, (file) => {
    csvFile = file;
    dom.csvFileName.textContent = file.name;
    dom.csvZone.classList.add('has-file');
    validateStep1();
});

wireUpload(dom.mediaZone, dom.mediaInput, (files) => {
    mediaFiles = files;
    dom.mediaFileNames.textContent = files.map(f => f.name).join(', ');
    dom.mediaZone.classList.add('has-file');
    validateStep2();
}, true);

wireUpload(dom.logoZone, dom.logoInput, (file) => {
    logoFile = file;
    dom.logoFileNames.textContent = file.name;
    dom.logoZone.classList.add('has-file');
});

wireUpload(dom.outroZone, dom.outroInput, (file) => {
    outroFile = file;
    dom.outroFileNames.textContent = file.name;
    dom.outroZone.classList.add('has-file');
});

wireUpload(dom.transitionZone, dom.transitionInput, (file) => {
    transitionFile = file;
    dom.transitionFileNames.textContent = file.name;
    dom.transitionZone.classList.add('has-file');
});

// ── Sliders ────────────────────────────────────────────────────────────
dom.silenceSlider.addEventListener('input', () => {
    dom.silenceVal.textContent = `${dom.silenceSlider.value}ms`;
});

dom.paddingSlider.addEventListener('input', () => {
    dom.paddingVal.textContent = `${dom.paddingSlider.value}ms`;
});

// ── Step 1: Process ────────────────────────────────────────────────────
dom.step1Btn.addEventListener('click', async () => {
    if (!videoFile || !csvFile) return;

    dom.step1Btn.disabled = true;
    showSection(dom.processingState);

    // Reset steps
    dom.processingSteps.querySelectorAll('.step').forEach(s => {
        s.classList.remove('step--active', 'step--done');
    });

    // Build form data
    const fd = new FormData();
    fd.append('video', videoFile);
    fd.append('csv_file', csvFile);
    fd.append('min_silence_ms', dom.silenceSlider.value);
    fd.append('silence_padding_ms', dom.paddingSlider.value);

    const apiKey = dom.apiKeyInput.value.trim();
    if (apiKey) fd.append('gemini_api_key', apiKey);

    const lang = dom.langSelect.value;
    if (lang) fd.append('language', lang);

    // Animate processing steps
    const steps = ['audio', 'transcribe', 'gemini', 'silence', 'xml'];
    let stepIdx = 0;

    const stepInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            if (stepIdx > 0) setStep(dom.processingSteps, steps[stepIdx - 1], 'done');
            setStep(dom.processingSteps, steps[stepIdx], 'active');
            stepIdx++;
        }
    }, 3000);

    try {
        const resp = await fetch('/api/explainer/step1', { method: 'POST', body: fd });
        clearInterval(stepInterval);

        // Mark all steps done
        steps.forEach(s => setStep(dom.processingSteps, s, 'done'));

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `Server error ${resp.status}`);
        }

        const data = await resp.json();
        jobId = data.job_id;
        requiredFiles = data.required_files || [];
        logoFile = null;
        outroFile = null;
        transitionFile = null;

        // Short delay to show completed steps, then show results
        await new Promise(r => setTimeout(r, 600));
        displayStep1Results(data);

    } catch (err) {
        clearInterval(stepInterval);
        showError(err.message);
    }
});

// ── Display Step 1 results ─────────────────────────────────────────────
function displayStep1Results(data) {
    showSection(dom.resultsState);

    // Stats
    dom.statScenes.textContent = data.total_scenes;
    dom.statOriginal.textContent = formatTime(data.original_duration);
    dom.statFinal.textContent = formatTime(data.final_duration);

    const saved = data.original_duration - data.final_duration;
    dom.statSaved.textContent = formatTime(Math.max(0, saved));

    // Token usage
    if (data.token_usage) {
        dom.tokenInfo.classList.remove('hidden');
        dom.tokIn.textContent = data.token_usage.input?.toLocaleString() || '—';
        dom.tokOut.textContent = data.token_usage.output?.toLocaleString() || '—';
        const total = (data.token_usage.input || 0) + (data.token_usage.output || 0);
        dom.tokTotal.textContent = total.toLocaleString();
    }

    // Scenes table
    dom.scenesBody.innerHTML = '';
    (data.scenes_summary || []).forEach(scene => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${scene.scene_number}</td>
            <td>${scene.total_takes}</td>
            <td class="mono">${formatTime(scene.selected_start)}</td>
            <td class="mono">${formatTime(scene.selected_end)}</td>
            <td class="mono">${scene.duration.toFixed(1)}s</td>
        `;
        dom.scenesBody.appendChild(tr);
    });

    // Download XML
    dom.downloadXml.href = data.download_url;
    dom.downloadXml.download = '';

    // SRT (available in step 1 only if no required files)
    if (data.srt_download_url) {
        dom.downloadSrt.href = data.srt_download_url;
        dom.downloadSrt.download = '';
        dom.downloadSrt.classList.remove('hidden');
    } else {
        dom.downloadSrt.classList.add('hidden');
    }

    // Show Step 2 if files are needed
    if (requiredFiles.length > 0) {
        showStep2(requiredFiles);
    }
}

// ── Show Step 2 ────────────────────────────────────────────────────────
function showStep2(files) {
    dom.step2Section.classList.remove('hidden');
    dom.step2Section.classList.add('anim-fade-up');

    const list = $('#requiredFilesList');
    if (files.length === 0) {
        list.innerHTML = `<p class="message message--info" data-i18n="no_media_needed">${t('no_media_needed')}</p>`;
        return;
    }

    list.innerHTML = `
        <p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:var(--space-sm)"
           data-i18n="required_files">${t('required_files')}</p>
        <div class="file-list">
            ${files.map(f => `
                <div class="file-list__item">
                    <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="1.5" fill="none">
                        <rect x="2" y="3" width="20" height="18" rx="2"/><path d="M10 8l6 4-6 4V8z"/>
                    </svg>
                    <span>${f}</span>
                </div>
            `).join('')}
        </div>
    `;

    // Scroll into view
    dom.step2Section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Step 2: Finalize ───────────────────────────────────────────────────
dom.step2Btn.addEventListener('click', async () => {
    if (!jobId || mediaFiles.length === 0) return;

    dom.step2Btn.disabled = true;
    showSection(dom.processingState2);

    // Reset steps
    dom.processingSteps2.querySelectorAll('.step').forEach(s => {
        s.classList.remove('step--active', 'step--done');
    });

    const fd = new FormData();
    fd.append('job_id', jobId);
    for (const file of mediaFiles) {
        fd.append('media_files', file);
    }
    if (logoFile) {
        fd.append('logo_file', logoFile);
    }
    if (outroFile) {
        fd.append('outro_file', outroFile);
    }
    if (transitionFile) {
        fd.append('transition_file', transitionFile);
    }

    // Animate processing steps
    const steps = ['broll', 'soundbite', 'srt'];
    let stepIdx = 0;

    const stepInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            if (stepIdx > 0) setStep(dom.processingSteps2, steps[stepIdx - 1], 'done');
            setStep(dom.processingSteps2, steps[stepIdx], 'active');
            stepIdx++;
        }
    }, 2500);

    try {
        const resp = await fetch('/api/explainer/step2', { method: 'POST', body: fd });
        clearInterval(stepInterval);

        steps.forEach(s => setStep(dom.processingSteps2, s, 'done'));

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `Server error ${resp.status}`);
        }

        const data = await resp.json();

        await new Promise(r => setTimeout(r, 600));
        displayStep2Results(data);

    } catch (err) {
        clearInterval(stepInterval);
        showError(err.message);
    }
});

// ── Display Step 2 results ─────────────────────────────────────────────
function displayStep2Results(data) {
    showSection(dom.resultsState);

    // Update downloads to final versions
    dom.downloadXml.href = data.download_url;
    dom.downloadXml.download = '';

    if (data.srt_download_url) {
        dom.downloadSrt.href = data.srt_download_url;
        dom.downloadSrt.download = '';
        dom.downloadSrt.classList.remove('hidden');
    }

    // Add B-roll/Soundbite stats if not already present
    const grid = $('#statsGrid');
    if (data.broll_count > 0 || data.soundbite_count > 0) {
        // Remove old media stats if re-running
        grid.querySelectorAll('.stat-card--media').forEach(el => el.remove());

        if (data.broll_count > 0) {
            const card = document.createElement('div');
            card.className = 'stat-card stat-card--media anim-fade-up';
            card.innerHTML = `<div class="stat-card__value">${data.broll_count}</div>
                <div class="stat-card__label" data-i18n="broll_count">${t('broll_count')}</div>`;
            grid.appendChild(card);
        }
        if (data.soundbite_count > 0) {
            const card = document.createElement('div');
            card.className = 'stat-card stat-card--media anim-fade-up';
            card.innerHTML = `<div class="stat-card__value">${data.soundbite_count}</div>
                <div class="stat-card__label" data-i18n="soundbite_count">${t('soundbite_count')}</div>`;
            grid.appendChild(card);
        }
    }

    // Warnings
    if (data.warnings && data.warnings.length > 0) {
        dom.warningsBox.classList.remove('hidden');
        dom.warningsBox.innerHTML = `
            <div class="message message--warning">
                <strong data-i18n="warnings">${t('warnings')}</strong>
                <ul style="margin:var(--space-xs) 0 0;padding-inline-start:1.2em;font-size:0.8rem">
                    ${data.warnings.map(w => `<li>${w}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    // Hide Step 2 section now that it's done
    dom.step2Section.classList.add('hidden');
}

// ── Error handling ─────────────────────────────────────────────────────
function showError(message) {
    showSection(dom.errorState);
    dom.errorMsg.textContent = message;
    dom.step1Btn.disabled = false;
    dom.step2Btn.disabled = false;
}

dom.retryBtn.addEventListener('click', () => {
    showSection(dom.emptyState);
    validateStep1();
    validateStep2();
});

// ── Theme toggle ───────────────────────────────────────────────────────
const theme = localStorage.getItem('smart-edit-theme') || 'dark';
document.documentElement.setAttribute('data-theme', theme);

$('#themeToggle').addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('smart-edit-theme', next);
    const icon = $('#themeIcon');
    icon.innerHTML = next === 'light'
        ? '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>'
        : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
});

// ── Language toggle ────────────────────────────────────────────────────
$('#langToggle').addEventListener('click', () => {
    setLang(getLang() === 'en' ? 'ar' : 'en');
});

// ── Init ───────────────────────────────────────────────────────────────
initI18n();
