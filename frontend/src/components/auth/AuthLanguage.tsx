"use client";

import { createContext, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";

export type AuthLanguage = "en" | "hi" | "gu";

/**
 * Languages offered by the selector, in display order. To add one, add its code to AuthLanguage,
 * an entry here and a full COPY entry below: the selector, search and persistence pick it up.
 * Only fully translated languages are listed, so a selection never shows a half-English page.
 */
export const AUTH_LANGUAGES: { code: AuthLanguage; englishName: string; nativeName: string }[] = [
  { code: "en", englishName: "English", nativeName: "English" },
  { code: "hi", englishName: "Hindi", nativeName: "हिन्दी" },
  { code: "gu", englishName: "Gujarati", nativeName: "ગુજરાતી" },
];

type AuthCopy = {
  language: string;
  searchLanguages: string;
  noLanguageMatch: string;
  forgotPassword: string;
  staffInvitationSetup: string;
  loading: string;
  createYourAccount: string;
  signupDescription: string;
  citizenOnlyNote: string;
  signInHere: string;
  fullName: string;
  phoneNumber: string;
  phoneHelp: string;
  choosePassword: string;
  passwordRules: [string, string, string];
  ruleDone: string;
  ruleNotYet: string;
  checkDetails: string;
  creatingAccount: string;
  createAccountArrow: string;
  alreadyHaveAccount: string;
  skipToForm: string;
  emergencySection: string;
  emergencyMessage: string;
  emergencyLabels: [string, string, string, string];
  callNumber: (number: string, label: string) => string;
  offlineMessage: string;
  liveMap: string;
  howTo: string;
  safetyGuidance: string;
  about: string;
  footer: string;
  signIn: string;
  loginDescription: string;
  email: string;
  password: string;
  show: string;
  hide: string;
  yourPassword: string;
  signingIn: string;
  signInArrow: string;
  staffMfaNote: string;
  newHere: string;
  createAccount: string;
  publicMapNote: string;
  publicMap: string;
  andRead: string;
  mfaStep: string;
  mfaInstruction: (email: string) => string;
  codeLabel: string;
  codeHelp: string;
  verifying: string;
  verifyAndContinue: string;
  useDifferentAccount: string;
  networkError: string;
  networkHint: string;
  lockedHint: string;
  incorrectCredentials: string;
  incorrectCredentialsHint: string;
};

const COPY: Record<AuthLanguage, AuthCopy> = {
  en: {
    language: "Language",
    searchLanguages: "Search languages",
    noLanguageMatch: "No language matches your search.",
    forgotPassword: "Forgot password?",
    staffInvitationSetup: "Staff invitation setup",
    loading: "Loading…",
    createYourAccount: "Create your account",
    signupDescription: "Free. It lets you report an incident and follow what happens next.",
    citizenOnlyNote: "Citizen accounts only. Staff and field-team accounts are issued by your administrator –",
    signInHere: "sign in here",
    fullName: "Full name",
    phoneNumber: "Phone number",
    phoneHelp: "(optional, helps responders reach you)",
    choosePassword: "Choose a password",
    passwordRules: ["At least 8 characters", "At least one number", "At least one symbol (for example ! @ # ?)"],
    ruleDone: "done",
    ruleNotYet: "not yet",
    checkDetails: "Check the details below and try again.",
    creatingAccount: "Creating account…",
    createAccountArrow: "Create account →",
    alreadyHaveAccount: "Already have an account?",
    skipToForm: "Skip to form",
    emergencySection: "Emergency numbers",
    emergencyMessage: "In danger? Call now – no sign-in needed.",
    emergencyLabels: ["Emergency", "Ambulance", "Fire", "Disaster helpline"],
    callNumber: (number, label) => `Call ${number}, ${label}`,
    offlineMessage: "You are offline. Reconnect to sign in. The emergency numbers above still work on your phone.",
    liveMap: "← Live map",
    howTo: "How to use ResQ",
    safetyGuidance: "Safety guidance",
    about: "About",
    footer: "ResQ · Disaster Response Coordination · Government of Gujarat",
    signIn: "Sign in",
    loginDescription: "For citizens, field teams and dispatch staff. Use the email and password you registered with.",
    email: "Email",
    password: "Password",
    show: "Show",
    hide: "Hide",
    yourPassword: "Your password",
    signingIn: "Signing in…",
    signInArrow: "Sign in →",
    staffMfaNote: "Dispatch and field staff will be asked for an authenticator code next.",
    newHere: "New here? Citizens can create a free account.",
    createAccount: "Create account",
    publicMapNote: "Can’t sign in right now? You can still view the",
    publicMap: "live public map",
    andRead: "and read the",
    mfaStep: "One more step",
    mfaInstruction: (email) => `Open your authenticator app and enter the 6-digit code for ${email}.`,
    codeLabel: "6-digit code",
    codeHelp: "The code changes every 30 seconds. If it fails, wait for the next one.",
    verifying: "Verifying…",
    verifyAndContinue: "Verify and continue →",
    useDifferentAccount: "Use a different account",
    networkError: "We could not reach the service.",
    networkHint: "Check your internet connection and try again in a moment.",
    lockedHint: "Wait a few minutes before trying again, or ask your team lead for help.",
    incorrectCredentials: "That email or password is not correct.",
    incorrectCredentialsHint: "Check for spaces or capital letters. Use “Show” to see what you typed.",
  },
  hi: {
    language: "भाषा",
    searchLanguages: "भाषा खोजें",
    noLanguageMatch: "आपकी खोज से कोई भाषा मेल नहीं खाती।",
    forgotPassword: "पासवर्ड भूल गए?",
    staffInvitationSetup: "स्टाफ आमंत्रण सेटअप",
    loading: "लोड हो रहा है…",
    createYourAccount: "अपना खाता बनाएँ",
    signupDescription: "निःशुल्क। इससे आप घटना की सूचना दे सकते हैं और आगे क्या होता है, यह देख सकते हैं।",
    citizenOnlyNote: "केवल नागरिक खाते। स्टाफ और फील्ड टीम के खाते आपके प्रशासक द्वारा दिए जाते हैं –",
    signInHere: "यहाँ साइन इन करें",
    fullName: "पूरा नाम",
    phoneNumber: "फ़ोन नंबर",
    phoneHelp: "(वैकल्पिक, इससे बचाव दल आपसे संपर्क कर सकता है)",
    choosePassword: "पासवर्ड चुनें",
    passwordRules: ["कम से कम 8 अक्षर", "कम से कम एक अंक", "कम से कम एक चिह्न (जैसे ! @ # ?)"],
    ruleDone: "पूरा",
    ruleNotYet: "अभी नहीं",
    checkDetails: "नीचे दी गई जानकारी जाँचें और फिर कोशिश करें।",
    creatingAccount: "खाता बनाया जा रहा है…",
    createAccountArrow: "खाता बनाएँ →",
    alreadyHaveAccount: "क्या आपका पहले से खाता है?",
    skipToForm: "फ़ॉर्म पर जाएँ",
    emergencySection: "आपातकालीन नंबर",
    emergencyMessage: "खतरे में हैं? अभी कॉल करें—साइन इन की ज़रूरत नहीं।",
    emergencyLabels: ["आपातकाल", "एम्बुलेंस", "अग्निशमन", "आपदा हेल्पलाइन"],
    callNumber: (number, label) => `${label}, ${number} पर कॉल करें`,
    offlineMessage: "आप ऑफ़लाइन हैं। साइन इन करने के लिए इंटरनेट से जुड़ें। ऊपर दिए गए आपातकालीन नंबर आपके फ़ोन से काम करते हैं।",
    liveMap: "← लाइव मानचित्र",
    howTo: "ResQ का उपयोग कैसे करें",
    safetyGuidance: "सुरक्षा मार्गदर्शन",
    about: "परिचय",
    footer: "ResQ · आपदा प्रतिक्रिया समन्वय · गुजरात सरकार",
    signIn: "साइन इन करें",
    loginDescription: "नागरिकों, फील्ड टीमों और डिस्पैच कर्मचारियों के लिए। अपने पंजीकृत ईमेल और पासवर्ड का उपयोग करें।",
    email: "ईमेल",
    password: "पासवर्ड",
    show: "दिखाएँ",
    hide: "छिपाएँ",
    yourPassword: "अपना पासवर्ड दर्ज करें",
    signingIn: "साइन इन हो रहा है…",
    signInArrow: "साइन इन करें →",
    staffMfaNote: "डिस्पैच और फील्ड कर्मचारियों से अगले चरण में ऑथेंटिकेटर कोड माँगा जाएगा।",
    newHere: "यहाँ नए हैं? नागरिक मुफ़्त खाता बना सकते हैं।",
    createAccount: "खाता बनाएँ",
    publicMapNote: "अभी साइन इन नहीं कर पा रहे? आप बिना खाते के",
    publicMap: "लाइव सार्वजनिक मानचित्र",
    andRead: "देख सकते हैं और",
    mfaStep: "एक और चरण",
    mfaInstruction: (email) => `${email} के लिए अपने ऑथेंटिकेटर ऐप में दिया गया 6 अंकों का कोड दर्ज करें।`,
    codeLabel: "6 अंकों का कोड",
    codeHelp: "कोड हर 30 सेकंड में बदलता है। काम न करे, तो अगले कोड की प्रतीक्षा करें।",
    verifying: "सत्यापन हो रहा है…",
    verifyAndContinue: "सत्यापित करें और आगे बढ़ें →",
    useDifferentAccount: "दूसरे खाते से साइन इन करें",
    networkError: "सेवा से संपर्क नहीं हो सका।",
    networkHint: "इंटरनेट कनेक्शन जाँचें और थोड़ी देर बाद फिर कोशिश करें।",
    lockedHint: "कुछ मिनट प्रतीक्षा करें या मदद के लिए अपनी टीम के प्रमुख से संपर्क करें।",
    incorrectCredentials: "ईमेल या पासवर्ड सही नहीं है।",
    incorrectCredentialsHint: "अतिरिक्त स्पेस या बड़े अक्षर जाँचें। आपने क्या टाइप किया है, यह देखने के लिए “दिखाएँ” चुनें।",
  },
  gu: {
    language: "ભાષા",
    searchLanguages: "ભાષા શોધો",
    noLanguageMatch: "તમારી શોધ સાથે કોઈ ભાષા મેળ ખાતી નથી.",
    forgotPassword: "પાસવર્ડ ભૂલી ગયા?",
    staffInvitationSetup: "સ્ટાફ આમંત્રણ સેટઅપ",
    loading: "લોડ થઈ રહ્યું છે…",
    createYourAccount: "તમારું ખાતું બનાવો",
    signupDescription: "મફત. તેનાથી તમે ઘટનાની જાણ કરી શકો છો અને આગળ શું થાય છે તે જોઈ શકો છો.",
    citizenOnlyNote: "ફક્ત નાગરિક ખાતાં. સ્ટાફ અને ફિલ્ડ ટીમનાં ખાતાં તમારા વ્યવસ્થાપક આપે છે –",
    signInHere: "અહીં સાઇન ઇન કરો",
    fullName: "પૂરું નામ",
    phoneNumber: "ફોન નંબર",
    phoneHelp: "(વૈકલ્પિક, તેનાથી બચાવ ટીમ તમારો સંપર્ક કરી શકે છે)",
    choosePassword: "પાસવર્ડ પસંદ કરો",
    passwordRules: ["ઓછામાં ઓછા 8 અક્ષરો", "ઓછામાં ઓછો એક અંક", "ઓછામાં ઓછું એક ચિહ્ન (ઉદાહરણ તરીકે ! @ # ?)"],
    ruleDone: "પૂર્ણ",
    ruleNotYet: "હજી નહીં",
    checkDetails: "નીચેની વિગતો તપાસો અને ફરી પ્રયાસ કરો.",
    creatingAccount: "ખાતું બની રહ્યું છે…",
    createAccountArrow: "ખાતું બનાવો →",
    alreadyHaveAccount: "પહેલેથી ખાતું છે?",
    skipToForm: "ફોર્મ પર જાઓ",
    emergencySection: "કટોકટીના નંબરો",
    emergencyMessage: "જોખમમાં છો? હમણાં કૉલ કરો—સાઇન ઇનની જરૂર નથી.",
    emergencyLabels: ["કટોકટી", "એમ્બ્યુલન્સ", "અગ્નિશમન", "આપત્તિ હેલ્પલાઇન"],
    callNumber: (number, label) => `${label} માટે ${number} પર કૉલ કરો`,
    offlineMessage: "તમે ઑફલાઇન છો. સાઇન ઇન કરવા માટે ફરીથી ઇન્ટરનેટ સાથે જોડાઓ. ઉપરના કટોકટીના નંબરો તમારા ફોનથી હજી પણ કામ કરે છે.",
    liveMap: "← લાઇવ નકશો",
    howTo: "ResQનો ઉપયોગ કેવી રીતે કરવો",
    safetyGuidance: "સલામતી માર્ગદર્શન",
    about: "વિશે",
    footer: "ResQ · આપત્તિ પ્રતિસાદ સંકલન · ગુજરાત સરકાર",
    signIn: "સાઇન ઇન કરો",
    loginDescription: "નાગરિકો, ફિલ્ડ ટીમો અને ડિસ્પેચ કર્મચારીઓ માટે. નોંધણી વખતે આપેલું ઇમેઇલ અને પાસવર્ડ વાપરો.",
    email: "ઇમેઇલ",
    password: "પાસવર્ડ",
    show: "બતાવો",
    hide: "છુપાવો",
    yourPassword: "તમારો પાસવર્ડ",
    signingIn: "સાઇન ઇન થઈ રહ્યું છે…",
    signInArrow: "સાઇન ઇન કરો →",
    staffMfaNote: "ડિસ્પેચ અને ફિલ્ડ કર્મચારીઓને આગળના તબક્કે ઑથેન્ટિકેટર કોડ પૂછવામાં આવશે.",
    newHere: "અહીં નવા છો? નાગરિકો મફત ખાતું બનાવી શકે છે.",
    createAccount: "ખાતું બનાવો",
    publicMapNote: "હમણાં સાઇન ઇન કરી શકતા નથી? તમે ખાતા વિના પણ",
    publicMap: "લાઇવ જાહેર નકશો",
    andRead: "જોઈ શકો છો અને",
    mfaStep: "એક વધુ પગલું",
    mfaInstruction: (email) => `${email} માટે તમારી ઑથેન્ટિકેટર ઍપમાં આવેલો 6 અંકનો કોડ દાખલ કરો.`,
    codeLabel: "6 અંકનો કોડ",
    codeHelp: "કોડ દર 30 સેકન્ડે બદલાય છે. કામ ન કરે તો આગલા કોડની રાહ જુઓ.",
    verifying: "ચકાસી રહ્યું છે…",
    verifyAndContinue: "ચકાસો અને આગળ વધો →",
    useDifferentAccount: "બીજા ખાતાથી સાઇન ઇન કરો",
    networkError: "સેવા સાથે જોડાઈ શકાયું નથી.",
    networkHint: "તમારું ઇન્ટરનેટ કનેક્શન તપાસો અને થોડી વારમાં ફરી પ્રયાસ કરો.",
    lockedHint: "ફરી પ્રયાસ કરતા પહેલાં થોડી મિનિટ રાહ જુઓ અથવા તમારી ટીમના લીડરનો સંપર્ક કરો.",
    incorrectCredentials: "આ ઇમેઇલ અથવા પાસવર્ડ સાચો નથી.",
    incorrectCredentialsHint: "વધારાની ખાલી જગ્યા અથવા મોટા અક્ષરો તપાસો. તમે શું લખ્યું છે તે જોવા માટે “બતાવો” પસંદ કરો.",
  },
};

const STORAGE_KEY = "resq-auth-language";
const LANGUAGE_CHANGE_EVENT = "resq-auth-language-change";

let languageSnapshot: AuthLanguage = "en";
let languageInitialized = false;

function getLanguageSnapshot(): AuthLanguage {
  if (!languageInitialized) {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved && isAuthLanguage(saved)) languageSnapshot = saved;
    } catch {
      // Storage may be unavailable; use English until the user selects a language.
    }
    languageInitialized = true;
  }
  return languageSnapshot;
}

function subscribeToLanguageChanges(callback: () => void) {
  const onStorage = () => {
    languageInitialized = false;
    callback();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(LANGUAGE_CHANGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(LANGUAGE_CHANGE_EVENT, callback);
  };
}

function updateLanguage(language: AuthLanguage) {
  languageSnapshot = language;
  languageInitialized = true;
  try {
    window.localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // Keep the in-memory selection if storage is unavailable.
  }
  window.dispatchEvent(new Event(LANGUAGE_CHANGE_EVENT));
}

type AuthLanguageContextValue = {
  language: AuthLanguage;
  setLanguage: (language: AuthLanguage) => void;
  copy: AuthCopy;
};

const AuthLanguageContext = createContext<AuthLanguageContextValue>({
  language: "en",
  setLanguage: () => {},
  copy: COPY.en,
});

function isAuthLanguage(value: string): value is AuthLanguage {
  return AUTH_LANGUAGES.some((language) => language.code === value);
}

export function AuthLanguageProvider({ children }: { children: ReactNode }) {
  const language = useSyncExternalStore(subscribeToLanguageChanges, getLanguageSnapshot, (): AuthLanguage => "en");
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <AuthLanguageContext.Provider value={{ language, setLanguage: updateLanguage, copy: COPY[language] }}>
      {children}
    </AuthLanguageContext.Provider>
  );
}

export function useAuthLanguage() {
  return useContext(AuthLanguageContext);
}

export function isSupportedAuthLanguage(value: string): value is AuthLanguage {
  return isAuthLanguage(value);
}
