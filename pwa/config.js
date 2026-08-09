// Vul in met de waarden uit Supabase > Project Settings > API.
// LET OP: hier hoort de *publishable* key (sb_publishable_...), nooit de secret
// key. De publishable key mag publiek zijn omdat RLS bepaalt wat een ingelogde
// gebruiker mag zien.
window.ASSISTANT_CONFIG = {
  supabaseUrl: "https://sfkcnfwgjwqrmtmcksxd.supabase.co",
  supabaseAnonKey: "sb_publishable_x-yQSM_95ynbNjTADPfDhQ_qX00Cuuv",
};
