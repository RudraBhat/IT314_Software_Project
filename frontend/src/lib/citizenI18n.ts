/**
 * ResQ Citizen Portal Internationalization (i18n)
 * Supports:
 *  - en: English (Default)
 *  - hi: हिन्दी (Hindi)
 *  - gu: ગુજરાતી (Gujarati)
 */

export type LanguageCode = "en" | "hi" | "gu";

export interface Translations {
  // Navigation & Header
  appTitle: string;
  portalSubtitle: string;
  publicUser: string;
  backendLive: string;
  /** Shown when the dashboard's data calls fail; there is no offline or local-storage mode. */
  backendUnreachable: string;
  signOut: string;
  notifications: string;
  markRead: string;
  markAllRead: string;
  noNotifications: string;
  fullMapView: string;
  close: string;

  // Welcome & Stats
  welcome: string;
  workspaceSubtitle: string;
  reportDisasterBtn: string;
  refreshBtn: string;
  myReportsCount: string;
  underReviewCount: string;
  verifiedCount: string;
  activeAlertsCount: string;

  // Tabs
  tabOverview: string;
  tabReport: string;
  tabMyReports: string;
  tabSafety: string;

  // SOS & Emergency
  sosButton: string;
  sosBroadcasting: string;
  sosSuccess: string;
  sosDisclaimer: string;
  activeAdvisories: string;
  helplineTitle: string;
  tollFree: string;
  call112: string;
  call108: string;
  call1077: string;
  call1070: string;

  // Map & Visuals
  liveMapTitle: string;
  liveMapSubtitle: string;
  recentActivityTitle: string;
  noReportsYet: string;
  reportNow: string;

  // Report Form
  formTitle: string;
  formSubtitle: string;
  selectDisasterType: string;
  disasterDescription: string;
  disasterDescPlaceholder: string;
  locationDetails: string;
  locationPlaceholder: string;
  gpsCoordinates: string;
  getGpsBtn: string;
  peopleAffected: string;
  urgentNeeds: string;
  submitting: string;
  submitReportBtn: string;
  reportSuccessMsg: string;

  // Disaster Categories
  catFlood: string;
  catCyclone: string;
  catFire: string;

  // Urgent Needs
  needBoats: string;
  needMedical: string;
  needWater: string;
  needShelter: string;
  needFood: string;
  needFireTenders: string;
  needPowerCutoff: string;

  // Status Badges
  statusPending: string;
  statusVerified: string;
  statusDispatched: string;
  statusResolved: string;
  statusClosed: string;
  statusRejected: string;

  // Safety Guidelines
  safetyTabTitle: string;
  safetyTabSubtitle: string;
  dosAndDonts: string;
  reliefShelters: string;
  noSheltersFound: string;
  capacityLabel: string;
}

export const TRANSLATIONS: Record<LanguageCode, Translations> = {
  en: {
    appTitle: "ResQ",
    portalSubtitle: "Citizen Safety Portal",
    publicUser: "Citizen User",
    backendLive: "Backend Live",
    backendUnreachable: "Server unreachable",
    signOut: "Sign Out",
    notifications: "Notifications",
    markRead: "Mark read",
    markAllRead: "Mark all as read",
    noNotifications: "No notifications yet.",
    fullMapView: "Full Map View",
    close: "Close",

    welcome: "Welcome",
    workspaceSubtitle:
      "Citizen Emergency & Disaster Response Workspace • Report emergencies, monitor active alerts, and track real-time resolution across Gujarat.",
    reportDisasterBtn: "Report Disaster",
    refreshBtn: "Refresh",
    myReportsCount: "My Reports",
    underReviewCount: "Under Review",
    verifiedCount: "Verified / Dispatched",
    activeAlertsCount: "Safety Advisories",

    tabOverview: "Dashboard Overview",
    tabReport: "Report a Disaster",
    tabMyReports: "My Reports",
    tabSafety: "Public Safety & Shelters",

    sosButton: "SOS Emergency Broadcast",
    sosBroadcasting: "Broadcasting SOS...",
    sosSuccess: "SOS Broadcast dispatched to Gujarat SEOC with your GPS location!",
    sosDisclaimer:
      "Use only in life-threatening emergencies. Immediately transmits your GPS coordinates to SEOC dispatchers.",
    activeAdvisories: "State Disaster Advisories (NDMA / SACHET)",
    helplineTitle: "24x7 Gujarat Emergency Helplines",
    tollFree: "Toll Free",
    call112: "112 - National Emergency (Police, Fire, Ambulance)",
    call108: "108 - Gujarat Emergency Medical & Ambulance",
    call1077: "1077 - District Disaster Control Room",
    call1070: "1070 - Gujarat State Disaster Management (GSDMA)",

    liveMapTitle: "Statewide Disaster Activity Map",
    liveMapSubtitle: "Verified incidents and alerts within Gujarat boundaries (privacy-protected)",
    recentActivityTitle: "Your Recent Incident Submissions",
    noReportsYet: "You haven't filed any disaster reports yet.",
    reportNow: "File an Emergency Report",

    formTitle: "Submit Disaster Incident",
    formSubtitle: "Provide precise details so Gujarat State Emergency responders can deploy aid swiftly.",
    selectDisasterType: "1. Disaster Type",
    disasterDescription: "2. Incident Description",
    disasterDescPlaceholder: "Describe the situation, water depth, trapped individuals, or specific hazards...",
    locationDetails: "3. Address or Landmark in Gujarat",
    locationPlaceholder: "e.g., Near Sardar Bridge, Adajan, Surat",
    gpsCoordinates: "GPS Coordinates (Gujarat Boundary Checked)",
    getGpsBtn: "Detect Current GPS",
    peopleAffected: "Estimated People Needing Assistance",
    urgentNeeds: "Urgent Relief Needs",
    submitting: "Transmitting Report...",
    submitReportBtn: "Submit Emergency Report →",
    reportSuccessMsg: "Report successfully submitted and forwarded to Gujarat Emergency Dispatch!",

    catFlood: "Flood / Urban Flood",
    catCyclone: "Cyclone / Coastal Flooding",
    catFire: "Major Urban / Building Fire",

    needBoats: "Rescue Boats",
    needMedical: "Medical Evacuation",
    needWater: "Drinking Water",
    needShelter: "Temporary Shelter",
    needFood: "Food Packets",
    needFireTenders: "Water Tenders (Fire)",
    needPowerCutoff: "Power Grid Cutoff",

    statusPending: "Under Review",
    statusVerified: "Verified by SEOC",
    statusDispatched: "Help Dispatched",
    statusResolved: "Incident Resolved",
    statusClosed: "Closed",
    statusRejected: "Rejected / Duplicate",

    safetyTabTitle: "Gujarat Public Safety & Relief Shelters",
    safetyTabSubtitle: "Official NDMA guidelines and active emergency evacuation relief shelters in Gujarat.",
    dosAndDonts: "Emergency Do's & Don'ts",
    reliefShelters: "Designated Relief Shelters",
    noSheltersFound: "No public shelters currently active in this sector.",
    capacityLabel: "Capacity",
  },

  hi: {
    appTitle: "ResQ",
    portalSubtitle: "नागरिक सुरक्षा पोर्टल",
    publicUser: "नागरिक उपयोगकर्ता",
    backendLive: "सर्वर सक्रिय",
    backendUnreachable: "सर्वर से संपर्क नहीं",
    signOut: "साइन आउट",
    notifications: "सूचनाएं",
    markRead: "पढ़ा हुआ चिह्नित करें",
    markAllRead: "सभी पढ़े हुए चिह्नित करें",
    noNotifications: "फिलहाल कोई सूचना नहीं है।",
    fullMapView: "विस्तृत नक्शा",
    close: "बंद करें",

    welcome: "नमस्ते",
    workspaceSubtitle:
      "नागरिक आपातकालीन एवं आपदा प्रबंधन पोर्टल • गुजरात भर में आपात स्थितियों की रिपोर्ट करें, अलर्ट देखें और राहत कार्य ट्रैक करें।",
    reportDisasterBtn: "आपदा रिपोर्ट करें",
    refreshBtn: "रिफ्रेश",
    myReportsCount: "मेरी रिपोर्ट्स",
    underReviewCount: "समीक्षाधीन",
    verifiedCount: "सत्यापित / प्रेषित",
    activeAlertsCount: "सुरक्षा चेतावनियां",

    tabOverview: "डैशबोर्ड अवलोकन",
    tabReport: "आपदा रिपोर्ट करें",
    tabMyReports: "मेरी रिपोर्ट्स",
    tabSafety: "सार्वजनिक सुरक्षा एवं आश्रय",

    sosButton: "आपातकालीन SOS प्रसारण",
    sosBroadcasting: "SOS प्रसारित हो रहा है...",
    sosSuccess: "गुजरात SEOC को आपके GPS स्थान के साथ आपातकालीन SOS भेज दिया गया है!",
    sosDisclaimer:
      "केवल जानलेवा आपात स्थिति में उपयोग करें। आपका GPS स्थान तुरंत आपदा कंट्रोल रूम को भेजा जाता है।",
    activeAdvisories: "राज्य आपदा चेतावनियां (NDMA / सचेत)",
    helplineTitle: "24x7 गुजरात आपातकालीन हेल्पलाइन",
    tollFree: "टोल फ्री",
    call112: "112 - राष्ट्रीय आपातकालीन (पुलिस, दमकल, एम्बुलेंस)",
    call108: "108 - गुजरात आपातकालीन एम्बुलेंस सेवा",
    call1077: "1077 - जिला आपदा नियंत्रण कक्ष",
    call1070: "1070 - राज्य आपदा प्रबंधन प्राधिकरण (GSDMA)",

    liveMapTitle: "राज्यव्यापी आपदा मानचित्र",
    liveMapSubtitle: "गुजरात के जिलों में सत्यापित घटनाएं एवं सुरक्षित क्षेत्र (गोपनीयता सुरक्षित)",
    recentActivityTitle: "आपकी हालिया रिपोर्टें",
    noReportsYet: "आपने अभी तक कोई आपदा रिपोर्ट दर्ज नहीं की है।",
    reportNow: "आपातकालीन रिपोर्ट दर्ज करें",

    formTitle: "आपदा घटना की रिपोर्ट दर्ज करें",
    formSubtitle: "सटीक जानकारी दें ताकि बचाव दल तेजी से सहायता पहुंचा सकें।",
    selectDisasterType: "1. आपदा का प्रकार",
    disasterDescription: "2. घटना का विवरण",
    disasterDescPlaceholder: "पानी का स्तर, फंसे हुए लोग, या तात्कालिक खतरे का विवरण दें...",
    locationDetails: "3. गुजरात में पता या लैंडमार्क",
    locationPlaceholder: "उदा., सरदार ब्रिज के पास, अडाजण, सूरत",
    gpsCoordinates: "GPS निर्देशांक (गुजरात राज्य सीमा सत्यापन)",
    getGpsBtn: "वर्तमान GPS प्राप्त करें",
    peopleAffected: "सहायता की आवश्यकता वाले अनुमानित लोग",
    urgentNeeds: "तत्काल राहत आवश्यकताएं",
    submitting: "रिपोर्ट भेजी जा रही है...",
    submitReportBtn: "आपातकालीन रिपोर्ट सबमिट करें →",
    reportSuccessMsg: "आपकी रिपोर्ट सफलतापूर्वक दर्ज कर गुजरात आपातकालीन नियंत्रण कक्ष को भेज दी गई है!",

    catFlood: "बाढ़ / जलभराव",
    catCyclone: "चक्रवात / तटीय तूफान",
    catFire: "आग दुर्घटना / इमारत में आग",

    needBoats: "बचाव नौकाएं",
    needMedical: "चिकित्सा सहायता / एयरलिफ्ट",
    needWater: "पीने का स्वच्छ पानी",
    needShelter: "अस्थायी आश्रय",
    needFood: "भोजन पैकेट",
    needFireTenders: "दमकल गाड़ियां (फायर टेंडर)",
    needPowerCutoff: "बिजली ग्रिड तत्काल बंद",

    statusPending: "समीक्षाधीन",
    statusVerified: "SEOC द्वारा सत्यापित",
    statusDispatched: "राहत दल रवाना",
    statusResolved: "घटना सुलझ गई",
    statusClosed: "बंद किया गया",
    statusRejected: "खारिज / डुप्लिकेट",

    safetyTabTitle: "गुजरात सार्वजनिक सुरक्षा एवं राहत आश्रय",
    safetyTabSubtitle: "आधिकारिक NDMA सुरक्षा निर्देश एवं गुजरात में सक्रिय राहत शिविर।",
    dosAndDonts: "आपदा में क्या करें और क्या न करें",
    reliefShelters: "नामित राहत आश्रय स्थल",
    noSheltersFound: "इस क्षेत्र में वर्तमान में कोई सक्रिय शिविर नहीं है।",
    capacityLabel: "क्षमता",
  },

  gu: {
    appTitle: "ResQ",
    portalSubtitle: "નાગરિક સુરક્ષા પોર્ટલ",
    publicUser: "જાહેર નાગરિક",
    backendLive: "સર્વર સક્રિય",
    backendUnreachable: "સર્વર સાથે સંપર્ક નથી",
    signOut: "સાઇન આઉટ",
    notifications: "સૂચનાઓ",
    markRead: "વાંચેલ તરીકે ચિહ્નિત કરો",
    markAllRead: "બધા વાંચેલા ચિહ્નિત કરો",
    noNotifications: "હજુ સુધી કોઈ સૂચના નથી.",
    fullMapView: "સંપૂર્ણ નકશો",
    close: "બંધ કરો",

    welcome: "સ્વાગત છે",
    workspaceSubtitle:
      "નાગરિક આપાતકાલીન અને આપત્તિ પ્રતિભાવ પ્લેટફોર્મ • ગુજરાતભરમાં આપત્તિની તાત્કાલિક જાણ કરો, એલર્ટ જુઓ અને સ્થિતિ ટ્રેક કરો.",
    reportDisasterBtn: "આપત્તિ રિપોર્ટ કરો",
    refreshBtn: "રીફ્રેશ",
    myReportsCount: "મારા રિપોર્ટ્સ",
    underReviewCount: "તપાસ હેઠળ",
    verifiedCount: "ચકાસાયેલ / ટીમ રવાના",
    activeAlertsCount: "સલામતી ચેતવણીઓ",

    tabOverview: "ડેશબોર્ડ ઝાંખી",
    tabReport: "આપત્તિ રિપોર્ટ કરો",
    tabMyReports: "મારા રિપોર્ટ્સ",
    tabSafety: "જાહેર સુરક્ષા અને આશ્રય",

    sosButton: "આપાતકાલીન SOS બ્રોડકાસ્ટ",
    sosBroadcasting: "SOS મોકલાઈ રહ્યું છે...",
    sosSuccess: "તમારા GPS લોકેશન સાથે ગુજરાત SEOC ને આપાતકાલીન SOS મોકલી દેવાયો છે!",
    sosDisclaimer:
      "માત્ર ગંભીર જીવન જોખમ સમયે જ ઉપયોગ કરવો. તમારું GPS લોકેશન સીધું આપત્તિ કંટ્રોલ રૂમને મોકલાય છે.",
    activeAdvisories: "રાજ્ય આપત્તિ ચેતવણીઓ (NDMA / સચેત)",
    helplineTitle: "24x7 ગુજરાત આપાતકાલીન હેલ્પલાઇન",
    tollFree: "ટોલ ફ્રી",
    call112: "112 - રાષ્ટ્રીય કટોકટી (પોલીસ, ફાયર, એમ્બ્યુલન્સ)",
    call108: "108 - ગુજરાત આપાતકાલીન એમ્બ્યુલન્સ સેવા",
    call1077: "1077 - જિલ્લા આપત્તિ નિયંત્રણ કક્ષ",
    call1070: "1070 - રાજ્ય આપત્તિ વ્યવસ્થાપન સત્તામંડળ (GSDMA)",

    liveMapTitle: "રાજ્યવ્યાપી આપત્તિ નકશો",
    liveMapSubtitle: "ગુજરાતના જિલ્લાઓમાં ચકાસાયેલ બનાવો અને સલામત વિસ્તારો (ગોપનીયતા સુરક્ષિત)",
    recentActivityTitle: "તમારા તાજેતરના અહેવાલો",
    noReportsYet: "તમે હજુ સુધી કોઈ આપત્તિ રિપોર્ટ નોંધાવ્યો નથી.",
    reportNow: "આપાતકાલીન રિપોર્ટ નોંધાવો",

    formTitle: "આપત્તિ ઘટનાની વિગત નોંધાવો",
    formSubtitle: "ચોક્કસ માહિતી આપો જેથી બચાવ દળ તાત્કાલિક સહાય પહોંચાડી શકે.",
    selectDisasterType: "1. આપત્તિનો પ્રકાર",
    disasterDescription: "2. ઘટનાનું વર્ણન",
    disasterDescPlaceholder: "પાણીનું સ્તર, ફસાયેલા લોકો, અથવા તાત્કાલિક જોખમની વિગત આપો...",
    locationDetails: "3. ગુજરાતમાં સરનામું અથવા ઓળખ ચિહ્ન",
    locationPlaceholder: "દા.ત., સરદાર બ્રિજ પાસે, અડાજણ, સુરત",
    gpsCoordinates: "GPS નિર્દેશાંક (ગુજરાત રાજ્ય સરહદ ચકાસણી)",
    getGpsBtn: "વર્તમાન GPS મેળવો",
    peopleAffected: "સહાયની જરૂરિયાતવાળા અંદાજિત લોકો",
    urgentNeeds: "તાત્કાલિક રાહત જરૂરિયાતો",
    submitting: "રિપોર્ટ મોકલાઈ રહ્યો છે...",
    submitReportBtn: "આપાતકાલીન રિપોર્ટ સબમિટ કરો →",
    reportSuccessMsg: "તમારો રિપોર્ટ સફળતાપૂર્વક નોંધીને ગુજરાત આપાતકાલીન કંટ્રોલ રૂમને મોકલી દેવાયો છે!",

    catFlood: "પૂર / શહેરી જળબંબાકાર",
    catCyclone: "વાવાઝોડું / દરિયાકાંઠાનું પૂર",
    catFire: "મોટી આગ દુર્ઘટના / ઈમારતમાં આગ",

    needBoats: "બચાવ હોડીઓ",
    needMedical: "તબીબી સહાય / એરલિફ્ટ",
    needWater: "પીવાનું શુદ્ધ પાણી",
    needShelter: "કામચલાઉ આશ્રય",
    needFood: "ભોજન પેકેટ",
    needFireTenders: "ફાયર ટેન્ડર (દમકલ વાહનો)",
    needPowerCutoff: "વીજળી ગ્રીડ તાત્કાલિક કટઓફ",

    statusPending: "તપાસ હેઠળ",
    statusVerified: "SEOC દ્વારા ચકાસાયેલ",
    statusDispatched: "મદદ ટીમ રવાના",
    statusResolved: "ઘટના ઉકેલાઈ ગઈ",
    statusClosed: "બંધ કરેલ",
    statusRejected: "નકારેલ / ડુપ્લિકેટ",

    safetyTabTitle: "ગુજરાત જાહેર સુરક્ષા અને રાહત શિબિરો",
    safetyTabSubtitle: "સત્તાવાર NDMA માર્ગદર્શિકા અને ગુજરાતમાં સક્રિય રાહત છાવણીઓ.",
    dosAndDonts: "આપત્તિ સમયે શું કરવું અને શું ન કરવું",
    reliefShelters: "નિયુક્ત રાહત આશ્રય સ્થાનો",
    noSheltersFound: "આ વિસ્તારમાં હાલમાં કોઈ સક્રિય આશ્રય સ્થાન નથી.",
    capacityLabel: "ક્ષમતા",
  },
};
