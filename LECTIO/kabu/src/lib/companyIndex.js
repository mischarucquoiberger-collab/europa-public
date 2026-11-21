// Company search index for the Reports search box and the ⌘K palette: US listed
// companies. The built-in list (src/data/companies.json, about 30 large US
// companies with their symbols and registered names) loads the first time the
// search box or the palette is used, as its own fingerprinted chunk; a backend
// may later send a longer list in the same row format.
//
// The curated "Popular" companies shown when the box is empty are kept inline
// (names exactly as in src/data/companies.json; a test keeps them in sync), so
// the empty dropdown opens without waiting for the list.

// Optional row fields a backend may still send: ``name_jp`` (a local-language
// name), ``aka`` (other names of the same symbol: former names, short names such
// as Google for Alphabet) and ``s`` (a size bucket, 0 = largest; ties rank by it).
// A query is matched on one normalised form of every name: NFKC (full-width
// letters and digits), lower case, kana folded to one form, company-type words
// and punctuation removed (coca-cola ↔ cocacola, amazon.com ↔ amazoncom).
// '&' is kept: it is part of names like AT&T, S&P and P&G, and dropping it would
// make 'p&g' the same query as 'pg'. A name with '&' also gets a key without it, so
// 'johnson johnson' still finds Johnson & Johnson; a query with '&' can only
// match keys that keep it.
const SMALL_KANA = { "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ", "ッ": "ツ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ", "ヵ": "カ", "ヶ": "ケ" };

/** One searchable form of a company name or a query (exported for tests). */
export function normalizeCompanyText(value) {
  let text = String(value || "").normalize("NFKC").toLowerCase();
  text = text.replace(/[\u3041-\u3096]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) + 0x60));
  text = text.replace(/[ァィゥェォッャュョヮヵヶ]/g, (ch) => SMALL_KANA[ch]);
  text = text.replace(/株式会社|\(株\)|合同会社|有限会社/g, "");
  return text.replace(/[\s・·.,，、。\-‐－—–_'’"“”()（）［］[\]/／!！?？:：]/g, "");
}

/** A name or query with its word breaks kept (one space between words), so
 *  'bank of' can rank Bank of America (whole first words) above a name whose
 *  spaceless key only happens to start with it. */
function spacedCompanyText(value) {
  return String(value || "").normalize("NFKC").toLowerCase()
    .replace(/[^\p{L}\p{N}&]+/gu, " ").trim();
}

// US listed symbols: 1 to 5 letters, optionally a share-class suffix written
// ".A"/".B" or "-A"/"-B" (BRK.B, BF-B). Typed in any case, shown and sent in capitals.
export const US_TICKER_RE = /^[A-Za-z]{1,5}(?:[.-][A-Za-z])?$/;

/** `raw` in capitals when it is shaped like a US symbol, else "". */
export function normalizeUsTicker(raw) {
  const text = String(raw || "").trim();
  return US_TICKER_RE.test(text) ? text.toUpperCase() : "";
}

// One comparable form of a symbol: capitals, '-' and '.' class separators alike (BRK-B = BRK.B).
const symbolKey = (value) => String(value || "").trim().toUpperCase().replace(/-/g, ".");

/**
 * The index row whose symbol is exactly `raw` (any case, either class
 * separator), or null. An ordinary word looks like a symbol too ('home',
 * 'apple'), so typed text counts as a ticker ONLY when the loaded index (the
 * built-in list or a list a backend sends) has that symbol.
 */
export function findIndexedTicker(index, raw) {
  const symbol = normalizeUsTicker(raw);
  if (!symbol) return null;
  const key = symbolKey(symbol);
  return (index || []).find((c) => (c.tickerKey || symbolKey(c.ticker)) === key) || null;
}

// Display case: a list may file names in capitals (WALT DISNEY CO) while a
// finished report carries Walt Disney Co. Both the dropdown and Recent show
// displayCompanyName(), so one company reads the same everywhere. Only an
// all-capitals Latin name is changed; acronyms stay capitals.
const KEEP_CAPITALS = new Set(["ETF", "ETN", "REIT", "JPX", "TSE", "TOPIX", "MSCI", "ESG", "JPY", "USD", "ICT", "IHI", "ANA", "JAL", "NEC", "AGC", "JFE",
  "SBI", "ABF", "ASJ", "TSI", "JCU", "IPS", "NOF", "INX", "KDDI", "MUFG", "SMBC", "ENEOS", "SCSK", "JTEC", "OTEC",
  "AI", "IT", "IC", "SK", "JM", "AP", "EM", "PS", "SD", "BR", "DY", "EX", "TV", "USA", "UK", "II", "III", "IV",
  // Listed names that are initials but contain a vowel (OSG, not Osg).
  "OSG", "TYK", "YKT", "MEC", "SEC", "ASB", "KEL", "AHC", "IMV", "LEC", "AMG", "EPO", "TRE", "PCA", "ISB", "NAC",
  "UEX", "AIT", "ES", "KU", "NZAM"]);
const LOWER_WORDS = new Set(["AND", "OF", "THE", "FOR", "IN", "ON", "DE"]);
const TITLE_WORDS = new Set(["LTD", "MFG", "CORP", "MFGCO", "CO", "INC"]);   // capitalised, never kept as acronyms

/** A company name as shown in lists (the stored and submitted name is unchanged). */
export function displayCompanyName(value) {
  const name = String(value || "").trim().replace(/\s+/g, " ").replace(/,(?=[^\s\d])/g, ", ");
  if (!/[A-Z]/.test(name) || /[a-z]/.test(name)) return name;
  return name.split(" ").map((word, index) => {
    const bare = word.replace(/[^A-Z0-9&]/g, "");
    if (KEEP_CAPITALS.has(bare) || KEEP_CAPITALS.has(bare.replace(/[0-9]+$/, ""))   // TOPIX-17
        || (!TITLE_WORDS.has(bare) && bare.length > 1 && !/[AEIOUY0-9&]/.test(bare))) return word;
    if (index > 0 && LOWER_WORDS.has(bare)) return word.toLowerCase();
    return word.toLowerCase().replace(/(^|[^a-z'’])([a-z])/g, (_, before, letter) => before + letter.toUpperCase());
  }).join(" ");
}

function entry(c) {
  const names = [c.name, c.name_jp, ...(Array.isArray(c.aka) ? c.aka : [])].filter(Boolean);
  const keys = names.map(normalizeCompanyText).filter(Boolean);
  const withoutAmp = keys.filter((k) => k.includes("&")).map((k) => k.replace(/&/g, "")).filter(Boolean);
  return {
    ...c,
    tickerLower: String(c.ticker || "").toLowerCase(),
    tickerKey: symbolKey(c.ticker),
    nameLower: String(c.name || "").toLowerCase(),
    searchKeys: [...new Set([...keys, ...withoutAmp])],
    spacedNames: [...new Set(names.map(spacedCompanyText).filter(Boolean))],
  };
}

/**
 * The index rows a lowercased query matches, best first: by symbol ('aapl',
 * 'brk.b', 'brk-b') and by any name containing it ('apple', 'micro'). A symbol
 * followed by its company's name, as in the placeholder's own 'AAPL   Apple
 * Inc.', finds that company. Ranks: the exact symbol or exact name; a name whose
 * first word(s) are the query ('apple' → Apple Inc.); a name or symbol starting
 * with it; a later word starting with it; a name or symbol merely containing it.
 * Ties go to the size bucket when a row has one, then the symbol. Shared by the
 * Reports search and the palette.
 */
export function matchCompanyIndex(index, q, limit = 20) {
  const raw = String(q || "").trim().toLowerCase();
  const query = normalizeCompanyText(raw);
  if (!query.replace(/&/g, "")) return [];   // empty, or only '&'
  const rows = index || [];
  const tokens = raw.normalize("NFKC").split(/[\s,]+/).filter(Boolean);
  if (tokens.length > 1) {
    // 'aapl apple inc', 'BRK.B Berkshire': a listed symbol, then words of its own name.
    const lead = findIndexedTicker(rows, tokens[0]);
    const rest = spacedCompanyText(tokens.slice(1).join(" "));
    if (lead && rest && (lead.spacedNames || [spacedCompanyText(lead.name)]).some((name) => name.includes(rest))) return [lead];
  }
  const symbol = symbolKey(raw);
  const spaced = spacedCompanyText(raw);
  const scored = [];
  for (const c of rows) {
    const keys = c.searchKeys || [normalizeCompanyText(c.name)];
    let rank = 5;
    const tickerKey = c.tickerKey || symbolKey(c.ticker);
    if (tickerKey === symbol) rank = 0;
    else if (tickerKey.startsWith(symbol)) rank = 2;
    for (const key of keys) {
      if (key === query) { rank = 0; break; }
      if (rank > 2 && key.startsWith(query)) rank = 2;
      else if (rank > 4 && key.includes(query)) rank = 4;
    }
    if (rank > 1 && spaced) {
      for (const name of c.spacedNames || [spacedCompanyText(c.name)]) {
        // The query's words are the name's first words; its last word may be
        // half typed ('bank of a') but a single word must be whole ('apple', not 'app').
        const next = name.charAt(spaced.length);
        if (name.startsWith(spaced) && (next === " " || (next && spaced.includes(" ")))) { rank = 1; break; }
        if (rank > 3 && name.includes(` ${spaced}`)) rank = 3;
      }
    }
    if (rank === 5 && (c.nameLower.includes(raw) || c.tickerLower.includes(raw))) rank = 4;
    if (rank < 5) scored.push([rank, Number.isInteger(c.s) ? c.s : 9, c]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2].tickerLower.localeCompare(b[2].tickerLower));
  return scored.slice(0, limit).map((item) => item[2]);
}

export const POPULAR_COMPANIES = [
  { ticker: "AAPL", name: "Apple Inc." },
  { ticker: "MSFT", name: "Microsoft Corporation" },
  { ticker: "NVDA", name: "NVIDIA Corporation" },
  { ticker: "AMZN", name: "Amazon.com, Inc." },
  { ticker: "GOOGL", name: "Alphabet Inc.", aka: ["Google"] },
  { ticker: "META", name: "Meta Platforms, Inc.", aka: ["Facebook"] },
  { ticker: "TSLA", name: "Tesla, Inc." },
  { ticker: "BRK.B", name: "Berkshire Hathaway Inc." },
  { ticker: "JPM", name: "JPMorgan Chase & Co." },
  { ticker: "V", name: "Visa Inc." },
  { ticker: "LLY", name: "Eli Lilly and Company" },
  { ticker: "AVGO", name: "Broadcom Inc." },
  { ticker: "WMT", name: "Walmart Inc." },
  { ticker: "XOM", name: "Exxon Mobil Corporation" },
  { ticker: "UNH", name: "UnitedHealth Group Incorporated" },
  { ticker: "MA", name: "Mastercard Incorporated" },
  { ticker: "JNJ", name: "Johnson & Johnson" },
  { ticker: "PG", name: "The Procter & Gamble Company" },
  { ticker: "COST", name: "Costco Wholesale Corporation" },
  { ticker: "KO", name: "The Coca-Cola Company" },
].map(entry);

let index = null;
let pending = null;

/** Builds the sorted search index from the raw list (exported for tests). */
export function buildCompanyIndex(companies) {
  return companies.map(entry).sort((a, b) => a.tickerLower.localeCompare(b.tickerLower));
}

/** The index if it has loaded, else null. */
export function companyIndexNow() {
  return index;
}

/** Loads the index once (a failed load is retried by the next call). */
export function loadCompanyIndex() {
  if (index) return Promise.resolve(index);
  if (!pending) {
    pending = import("@/data/companies.json")
      .then((module) => { index = buildCompanyIndex(module.default); return index; })
      .catch((error) => { pending = null; throw error; });
  }
  return pending;
}
