/**
 * Smart Editing — Frontend logic
 * Handles video upload, settings, processing, and results display.
 * No script needed - auto-detects scenes from audio.
 */

// DOM elements
const videoZone = document.getElementById('videoZone');
const videoInput = document.getElementById('videoInput');
const videoFileName = document.getElementById('videoFileName');

const scriptZone = document.getElementById('scriptZone');
const scriptInput = document.getElementById('scriptInput');
const scriptFileName = document.getElementById('scriptFileName');

const silenceSlider = document.getElementById('silenceSlider');
const silenceValue = document.getElementById('silenceValue');
const paddingSlider = document.getElementById('paddingSlider');
const paddingValue = document.getElementById('paddingValue');
const geminiApiKey = document.getElementById('geminiApiKey');
const apiKeyToggle = document.getElementById('apiKeyToggle');
const languageSelect = document.getElementById('languageSelect');
const processBtn = document.getElementById('processBtn');
const statusIndicator = document.getElementById('statusIndicator');

const emptyState = document.getElementById('emptyState');
const processingState = document.getElementById('processingState');
const resultsState = document.getElementById('resultsState');
const errorState = document.getElementById('errorState');

const processingStep = document.getElementById('processingStep');
const downloadBtn = document.getElementById('downloadBtn');
const srtDownloadBtn = document.getElementById('srtDownloadBtn');
const retryBtn = document.getElementById('retryBtn');
const errorMessage = document.getElementById('errorMessage');

// State
let videoFile = null;
let scriptFile = null;
let currentJobId = null;
let brollFiles = [];
let brollInstructionsFile = null;

// ---- File upload handling ----

function setupUploadZone(zone, input, fileNameEl, onFileSet) {
    zone.addEventListener('click', () => input.click());

    input.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            onFileSet(e.target.files[0]);
            fileNameEl.textContent = e.target.files[0].name;
            zone.classList.add('has-file');
        }
    });

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
        if (e.dataTransfer.files.length > 0) {
            const file = e.dataTransfer.files[0];
            onFileSet(file);
            fileNameEl.textContent = file.name;
            zone.classList.add('has-file');
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
        }
    });
}

setupUploadZone(videoZone, videoInput, videoFileName, (file) => {
    videoFile = file;
    updateProcessBtn();
});

setupUploadZone(scriptZone, scriptInput, scriptFileName, (file) => {
    scriptFile = file;
});

function updateProcessBtn() {
    // API key is optional in frontend (can come from .env on server)
    processBtn.disabled = !videoFile;
}

geminiApiKey.addEventListener('input', updateProcessBtn);

// Toggle API key visibility
apiKeyToggle.addEventListener('click', () => {
    geminiApiKey.type = geminiApiKey.type === 'password' ? 'text' : 'password';
});

// ---- Sliders ----

silenceSlider.addEventListener('input', () => {
    const val = (silenceSlider.value / 1000).toFixed(1);
    silenceValue.textContent = `${val} ث`;
});

paddingSlider.addEventListener('input', () => {
    paddingValue.textContent = `${paddingSlider.value} مل/ث`;
});

// ---- State management ----

function showState(state) {
    emptyState.classList.add('hidden');
    processingState.classList.add('hidden');
    resultsState.classList.add('hidden');
    errorState.classList.add('hidden');
    state.classList.remove('hidden');
}

function setStatus(text, type = 'ready') {
    const dot = statusIndicator.querySelector('.status-dot');
    const label = statusIndicator.querySelector('.status-text');
    label.textContent = text;

    dot.classList.remove('processing', 'error');
    if (type === 'processing') dot.classList.add('processing');
    if (type === 'error') dot.classList.add('error');
}

// ---- Processing steps animation ----

const STEPS = [
    'استخراج الصوت',
    'النسخ الصوتي',
    'تحليل Gemini AI',
    'حذف السكتات',
    'توليد الملف',
];

let stepInterval = null;

function startStepsAnimation() {
    const stepEls = document.querySelectorAll('.step:not(.hidden)');
    let current = 0;

    stepEls.forEach(el => {
        el.classList.remove('active', 'done');
    });

    function advanceStep() {
        if (current > 0 && current <= stepEls.length) {
            stepEls[current - 1].classList.remove('active');
            stepEls[current - 1].classList.add('done');
        }
        if (current < stepEls.length) {
            stepEls[current].classList.add('active');
            processingStep.textContent = STEPS[current];
            current++;
        } else {
            clearInterval(stepInterval);
        }
    }

    advanceStep();
    stepInterval = setInterval(advanceStep, 3000);
}

function stopStepsAnimation() {
    if (stepInterval) {
        clearInterval(stepInterval);
        stepInterval = null;
    }
    document.querySelectorAll('.step').forEach(el => {
        el.classList.remove('active');
        el.classList.add('done');
    });
}

// ---- Format time ----

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    if (mins > 0) {
        return `${mins}:${secs.padStart(4, '0')}`;
    }
    return `${secs}s`;
}

function formatTimecode(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const frames = Math.floor((seconds % 1) * 30);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}:${String(frames).padStart(2, '0')}`;
}

// ---- Process ----

processBtn.addEventListener('click', async () => {
    if (!videoFile) return;

    processBtn.disabled = true;

    // Show/hide B-Roll step indicator
    const brollStepEl = document.getElementById('brollStep');
    if (hasBrollReady()) {
        brollStepEl.classList.remove('hidden');
    } else {
        brollStepEl.classList.add('hidden');
    }

    // Reset B-Roll results from previous run
    brollResults.classList.add('hidden');

    showState(processingState);
    setStatus('جاري المعالجة...', 'processing');
    startStepsAnimation();

    const formData = new FormData();
    formData.append('video', videoFile);
    if (scriptFile) {
        formData.append('script', scriptFile);
    }
    formData.append('gemini_api_key', geminiApiKey.value.trim());
    formData.append('language', languageSelect.value);
    formData.append('min_silence_ms', silenceSlider.value);
    formData.append('silence_padding_ms', paddingSlider.value);

    try {
        // Phase 1: Main video processing
        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'حدث خطأ في المعالجة');
        }

        stopStepsAnimation();
        displayResults(data);

        // Phase 2: Auto-chain B-Roll (if files provided)
        if (hasBrollReady()) {
            brollStepEl.classList.add('active');
            processingStep.textContent = 'إضافة البي رول';
            setStatus('جاري إضافة البي رول...', 'processing');

            try {
                const brollData = await processBroll(data.job_id);
                brollStepEl.classList.remove('active');
                brollStepEl.classList.add('done');
                displayBrollResults(brollData);
            } catch (brollErr) {
                brollStepEl.classList.remove('active');
                // Show B-Roll error as warning, don't fail main results
                document.getElementById('brollCount').textContent = 'فشل في إضافة البي رول';
                const warningsEl = document.getElementById('brollWarnings');
                warningsEl.innerHTML = `<div class="broll-warning">${brollErr.message}</div>`;
                warningsEl.classList.remove('hidden');
                brollResults.classList.remove('hidden');
            }
        }

        showState(resultsState);
        setStatus('تم بنجاح', 'ready');

    } catch (err) {
        stopStepsAnimation();
        errorMessage.textContent = err.message;
        showState(errorState);
        setStatus('خطأ', 'error');
    } finally {
        processBtn.disabled = false;
    }
});

// ---- Display results ----

function displayResults(data) {
    currentJobId = data.job_id;
    document.getElementById('statScenes').textContent = data.total_scenes;
    document.getElementById('statOriginal').textContent = formatTime(data.original_duration);
    document.getElementById('statFinal').textContent = formatTime(data.final_duration);

    const savedPercent = data.original_duration > 0
        ? Math.round((1 - data.final_duration / data.original_duration) * 100)
        : 0;
    document.getElementById('statSaved').textContent = `${savedPercent}%`;

    // Token usage
    const tokenEl = document.getElementById('tokenUsage');
    if (data.token_usage) {
        document.getElementById('tokenInput').textContent = data.token_usage.input_tokens.toLocaleString();
        document.getElementById('tokenOutput').textContent = data.token_usage.output_tokens.toLocaleString();
        document.getElementById('tokenTotal').textContent = data.token_usage.total_tokens.toLocaleString();
        tokenEl.classList.remove('hidden');
    } else {
        tokenEl.classList.add('hidden');
    }

    const tbody = document.getElementById('scenesTableBody');
    tbody.innerHTML = '';

    data.scenes_summary.forEach((scene) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>مشهد ${scene.scene_number}</td>
            <td><span class="take-count">${scene.total_takes}</span></td>
            <td class="time-cell">${formatTimecode(scene.selected_start)}</td>
            <td class="time-cell">${formatTimecode(scene.selected_end)}</td>
            <td class="time-cell">${formatTime(scene.duration)}</td>
        `;
        tbody.appendChild(tr);
    });

    downloadBtn.href = data.download_url;
    srtDownloadBtn.href = data.srt_download_url;
}

// ---- Retry ----

retryBtn.addEventListener('click', () => {
    showState(emptyState);
    setStatus('جاهز', 'ready');
    updateProcessBtn();
    // Reset B-Roll results
    brollResults.classList.add('hidden');
    document.getElementById('brollWarnings').classList.add('hidden');
});

// ---- B-Roll ----

const brollZone = document.getElementById('brollZone');
const brollInput = document.getElementById('brollInput');
const brollFileNames = document.getElementById('brollFileNames');
const brollInstructionsZone = document.getElementById('brollInstructionsZone');
const brollInstructionsInput = document.getElementById('brollInstructionsInput');
const brollInstructionsFileName = document.getElementById('brollInstructionsFileName');
const brollResults = document.getElementById('brollResults');

// Multi-file upload for B-Roll videos
brollZone.addEventListener('click', () => brollInput.click());

brollInput.addEventListener('change', (e) => {
    brollFiles = Array.from(e.target.files);
    if (brollFiles.length > 0) {
        brollFileNames.textContent = brollFiles.map(f => f.name).join('، ');
        brollZone.classList.add('has-file');
    }
});

brollZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    brollZone.classList.add('dragover');
});

brollZone.addEventListener('dragleave', () => {
    brollZone.classList.remove('dragover');
});

brollZone.addEventListener('drop', (e) => {
    e.preventDefault();
    brollZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        brollFiles = Array.from(e.dataTransfer.files);
        brollFileNames.textContent = brollFiles.map(f => f.name).join('، ');
        brollZone.classList.add('has-file');
        const dt = new DataTransfer();
        brollFiles.forEach(f => dt.items.add(f));
        brollInput.files = dt.files;
    }
});

// Instructions file (single file)
setupUploadZone(brollInstructionsZone, brollInstructionsInput, brollInstructionsFileName, (file) => {
    brollInstructionsFile = file;
});

// ---- B-Roll auto-chain helpers ----

function hasBrollReady() {
    return brollFiles.length > 0 && brollInstructionsFile !== null;
}

async function processBroll(jobId) {
    const formData = new FormData();
    formData.append('job_id', jobId);
    for (const file of brollFiles) {
        formData.append('broll_files', file);
    }
    formData.append('instructions_file', brollInstructionsFile);

    const response = await fetch('/api/add-broll', {
        method: 'POST',
        body: formData,
    });

    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'خطأ في إضافة البي رول');
    }
    return data;
}

function displayBrollResults(data) {
    document.getElementById('brollCount').textContent =
        `تمت إضافة ${data.broll_count} مقطع بي رول بنجاح`;

    const warningsEl = document.getElementById('brollWarnings');
    if (data.warnings && data.warnings.length > 0) {
        warningsEl.innerHTML = data.warnings
            .map(w => `<div class="broll-warning">${w}</div>`)
            .join('');
        warningsEl.classList.remove('hidden');
    } else {
        warningsEl.classList.add('hidden');
    }

    document.getElementById('brollDownloadBtn').href = data.download_url;
    brollResults.classList.remove('hidden');
}
