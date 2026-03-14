/* Internationalization strings - Arabic & English */

export const STRINGS = {
    ar: {
        // Header
        app_title: "Smart Editing",
        brand_subtitle: "تحرير ذكي",

        // Landing
        landing_title: "Smart Editing",
        landing_subtitle: "خدمات المونتاج الذكي للمراسلين",
        service_explainer: "Explainer",
        service_explainer_desc: "معالجة تقارير المراسلين تلقائياً وإنشاء تايملاين جاهز للمونتاج مع B-Roll و Sound Bites",

        // Explainer - Step 1
        step1_title: "الخطوة 1",
        step1_subtitle: "الفيديو والسكريبت",
        upload_video: "ارفع ملف الفيديو",
        upload_video_hint: "MP4, MOV, MKV, AVI",
        upload_csv: "ارفع ملف CSV",
        upload_csv_hint: "قالب السكريبت الموحد",
        download_template: "تحميل القالب",
        settings: "الإعدادات",
        silence_min: "حد أدنى للصمت",
        silence_padding: "هامش الصمت",
        api_key: "مفتاح Gemini API",
        api_key_placeholder: "أدخل المفتاح أو اتركه فارغاً لاستخدام .env",
        language: "اللغة",
        lang_auto: "تلقائي",
        lang_ar: "عربي",
        lang_en: "English",
        btn_process: "ابدأ المعالجة",

        // Explainer - Step 2
        step2_title: "الخطوة 2",
        step2_subtitle: "ملفات B-Roll و Sound Bites",
        required_files: "الملفات المطلوبة",
        upload_media: "ارفع الملفات",
        upload_media_hint: "اسحب جميع ملفات الفيديو المطلوبة هنا",
        upload_logo: "ارفع اللوجو (اختياري)",
        upload_outro: "ارفع الخاتمة (اختياري)",
        upload_transition: "ارفع ملف الانتقال (اختياري)",
        btn_finalize: "إنهاء المعالجة",
        no_media_needed: "لا يوجد ملفات مطلوبة - السكريبت لا يحتوي على B-Roll أو Sound Bites",

        // Processing
        processing_title: "جاري المعالجة",
        step_audio: "استخراج الصوت",
        step_transcribe: "تفريغ النص",
        step_gemini: "تحليل Gemini AI",
        step_silence: "إزالة الصمت",
        step_xml: "إنشاء XML",
        step_broll: "إضافة B-Roll",
        step_soundbite: "إضافة Sound Bites",
        step_srt: "إنشاء الترجمة",

        // Results
        results_title: "النتائج",
        scenes: "المشاهد",
        original_duration: "المدة الأصلية",
        final_duration: "المدة النهائية",
        time_saved: "الوقت المحفوظ",
        broll_count: "B-Roll",
        soundbite_count: "Sound Bites",
        download_xml: "تحميل XML",
        download_srt: "تحميل SRT",
        scene_num: "#",
        takes: "Takes",
        start: "البداية",
        end: "النهاية",
        duration: "المدة",
        warnings: "تحذيرات",
        tokens: "Tokens",
        token_input: "إدخال",
        token_output: "إخراج",
        token_total: "إجمالي",

        // States
        empty_title: "ابدأ بالخطوة 1",
        empty_desc: "ارفع الفيديو وملف CSV لبدء المعالجة",
        error_title: "حدث خطأ",
        btn_retry: "إعادة المحاولة",
    },
    en: {
        // Header
        app_title: "Smart Editing",
        brand_subtitle: "Smart Editing",

        // Landing
        landing_title: "Smart Editing",
        landing_subtitle: "Smart editing services for reporters",
        service_explainer: "Explainer",
        service_explainer_desc: "Auto-process reporter recordings and generate edit-ready timeline with B-Roll & Sound Bites",

        // Explainer - Step 1
        step1_title: "Step 1",
        step1_subtitle: "Video & Script",
        upload_video: "Upload video file",
        upload_video_hint: "MP4, MOV, MKV, AVI",
        upload_csv: "Upload CSV file",
        upload_csv_hint: "Unified script template",
        download_template: "Download template",
        settings: "Settings",
        silence_min: "Min silence",
        silence_padding: "Silence padding",
        api_key: "Gemini API Key",
        api_key_placeholder: "Enter key or leave empty for .env",
        language: "Language",
        lang_auto: "Auto",
        lang_ar: "Arabic",
        lang_en: "English",
        btn_process: "Start Processing",

        // Explainer - Step 2
        step2_title: "Step 2",
        step2_subtitle: "B-Roll & Sound Bite Files",
        required_files: "Required files",
        upload_media: "Upload files",
        upload_media_hint: "Drag all required video files here",
        upload_logo: "Upload Logo (optional)",
        upload_outro: "Upload Outro (optional)",
        upload_transition: "Upload Transition (optional)",
        btn_finalize: "Finalise Processing",
        no_media_needed: "No media files needed - script has no B-Roll or Sound Bites",

        // Processing
        processing_title: "Processing",
        step_audio: "Extracting audio",
        step_transcribe: "Transcribing",
        step_gemini: "Gemini AI analysis",
        step_silence: "Removing silence",
        step_xml: "Generating XML",
        step_broll: "Adding B-Roll",
        step_soundbite: "Adding Sound Bites",
        step_srt: "Generating subtitles",

        // Results
        results_title: "Results",
        scenes: "Scenes",
        original_duration: "Original",
        final_duration: "Final",
        time_saved: "Saved",
        broll_count: "B-Roll",
        soundbite_count: "Sound Bites",
        download_xml: "Download XML",
        download_srt: "Download SRT",
        scene_num: "#",
        takes: "Takes",
        start: "Start",
        end: "End",
        duration: "Duration",
        warnings: "Warnings",
        tokens: "Tokens",
        token_input: "Input",
        token_output: "Output",
        token_total: "Total",

        // States
        empty_title: "Start with Step 1",
        empty_desc: "Upload video and CSV file to begin processing",
        error_title: "An error occurred",
        btn_retry: "Retry",
    },
};
