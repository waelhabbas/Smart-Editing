/* Internationalization - Language switching */

import { STRINGS } from './strings.js';

let currentLang = localStorage.getItem('smart-edit-lang') || 'en';

export function getLang() {
    return currentLang;
}

export function t(key) {
    return STRINGS[currentLang]?.[key] || STRINGS.en[key] || key;
}

export function setLang(lang) {
    currentLang = lang;
    localStorage.setItem('smart-edit-lang', lang);
    document.documentElement.setAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
    document.documentElement.setAttribute('lang', lang);
    applyStrings();
}

export function applyStrings() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        const text = t(key);
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            el.placeholder = text;
        } else {
            el.textContent = text;
        }
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.getAttribute('data-i18n-title'));
    });
}

export function initI18n() {
    document.documentElement.setAttribute('dir', currentLang === 'ar' ? 'rtl' : 'ltr');
    document.documentElement.setAttribute('lang', currentLang);
    applyStrings();
}
