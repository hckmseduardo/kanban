import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

// Import English translations
import enCommon from './locales/en/common.json'
import enAuth from './locales/en/auth.json'
import enTeams from './locales/en/teams.json'
import enWorkspaces from './locales/en/workspaces.json'

// Import French (Quebec) translations
import frCACommon from './locales/fr-CA/common.json'
import frCAAuth from './locales/fr-CA/auth.json'
import frCATeams from './locales/fr-CA/teams.json'
import frCAWorkspaces from './locales/fr-CA/workspaces.json'

// Import Portuguese translations
import ptCommon from './locales/pt/common.json'
import ptAuth from './locales/pt/auth.json'
import ptTeams from './locales/pt/teams.json'
import ptWorkspaces from './locales/pt/workspaces.json'

// Import Spanish translations
import esCommon from './locales/es/common.json'
import esAuth from './locales/es/auth.json'
import esTeams from './locales/es/teams.json'
import esWorkspaces from './locales/es/workspaces.json'

// Import Chinese translations
import zhCommon from './locales/zh/common.json'
import zhAuth from './locales/zh/auth.json'
import zhTeams from './locales/zh/teams.json'
import zhWorkspaces from './locales/zh/workspaces.json'

// Import Arabic translations
import arCommon from './locales/ar/common.json'
import arAuth from './locales/ar/auth.json'
import arTeams from './locales/ar/teams.json'
import arWorkspaces from './locales/ar/workspaces.json'

export const supportedLanguages = [
  { code: 'en', name: 'English', flag: '🇺🇸' },
  { code: 'fr-CA', name: 'Français (Québec)', flag: '🇨🇦' },
  { code: 'pt', name: 'Português', flag: '🇧🇷' },
  { code: 'es', name: 'Español', flag: '🇪🇸' },
  { code: 'zh', name: '中文', flag: '🇨🇳' },
  { code: 'ar', name: 'العربية', flag: '🇸🇦', rtl: true }
] as const

export type LanguageCode = typeof supportedLanguages[number]['code']

// Get cookie domain for cross-subdomain sharing
const getCookieDomain = (): string => {
  if (typeof window === 'undefined') return ''
  const hostname = window.location.hostname
  if (hostname === 'localhost' || hostname === '127.0.0.1') return ''
  const parts = hostname.split('.')
  if (parts.length >= 3) {
    return '.' + parts.slice(-3).join('.')
  }
  return '.' + hostname
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { common: enCommon, auth: enAuth, teams: enTeams, workspaces: enWorkspaces },
      'fr-CA': { common: frCACommon, auth: frCAAuth, teams: frCATeams, workspaces: frCAWorkspaces },
      pt: { common: ptCommon, auth: ptAuth, teams: ptTeams, workspaces: ptWorkspaces },
      es: { common: esCommon, auth: esAuth, teams: esTeams, workspaces: esWorkspaces },
      zh: { common: zhCommon, auth: zhAuth, teams: zhTeams, workspaces: zhWorkspaces },
      ar: { common: arCommon, auth: arAuth, teams: arTeams, workspaces: arWorkspaces }
    },
    fallbackLng: 'en',
    supportedLngs: ['en', 'fr-CA', 'pt', 'es', 'zh', 'ar'],
    ns: ['common', 'auth', 'teams', 'workspaces'],
    defaultNS: 'common',
    detection: {
      order: ['cookie', 'navigator'],
      caches: ['cookie'],
      lookupCookie: 'lang',
      cookieDomain: getCookieDomain(),
      cookieOptions: { path: '/', sameSite: 'lax' }
    },
    interpolation: {
      escapeValue: false
    }
  })

// Update document direction when language changes
i18n.on('languageChanged', (lng) => {
  const isRTL = lng === 'ar'
  document.documentElement.dir = isRTL ? 'rtl' : 'ltr'
  document.documentElement.lang = lng
})

// Set initial direction
const isRTL = i18n.language === 'ar'
document.documentElement.dir = isRTL ? 'rtl' : 'ltr'
document.documentElement.lang = i18n.language

export default i18n
