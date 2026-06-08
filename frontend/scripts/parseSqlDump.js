/**
 * parseSqlDump.js
 * Parses local_backup_2026_06_04.sql and generates src/data/billsData.js
 * Run: node scripts/parseSqlDump.js
 */
const fs = require('fs');
const path = require('path');

const SQL_FILE = path.join(__dirname, '../../local_backup_2026_06_04.sql');
const OUTPUT_FILE = path.join(__dirname, '../src/data/billsData.js');

// ── helpers ──────────────────────────────────────────────────────────────────

function nullify(val) {
  return val === '\\N' ? null : val;
}

// Find the line index right after "COPY public.<table> ... FROM stdin;"
function findCopyStart(lines, tableName) {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith(`COPY public.${tableName} `)) return i + 1;
  }
  return -1;
}

// Read all TSV rows from a COPY block until "\."
function parseCopyBlock(lines, startIdx) {
  const rows = [];
  for (let i = startIdx; i < lines.length; i++) {
    const line = lines[i];
    if (line === '\\.' || line === '\\.') break;
    rows.push(line.split('\t'));
  }
  return rows;
}

// Extract sponsor fullName using regex (avoids full JSON.parse on huge blobs)
function extractSponsor(apiRaw) {
  try {
    const nameMatch = apiRaw.match(/"fullName":\s*"([^"]+)"/);
    const partyMatch = apiRaw.match(/"party":\s*"([A-Z])"/);
    const stateMatch = apiRaw.match(/"state":\s*"([A-Z]{2})"/);
    return {
      sponsor_name: nameMatch ? nameMatch[1] : null,
      sponsor_party: partyMatch ? partyMatch[1] : null,
      sponsor_state: stateMatch ? stateMatch[1] : null,
    };
  } catch {
    return { sponsor_name: null, sponsor_party: null, sponsor_state: null };
  }
}

// ── main ─────────────────────────────────────────────────────────────────────

console.log('Reading SQL dump...');
const content = fs.readFileSync(SQL_FILE, 'utf-8');
const lines = content.split('\n').map(l => l.replace(/\r$/, ''));
console.log(`  ${lines.length} lines loaded`);

// 1. animal_subjects  →  id → subject_name
console.log('Parsing animal_subjects...');
const asStart = findCopyStart(lines, 'animal_subjects');
const animalSubjectRows = parseCopyBlock(lines, asStart);
const subjectMap = {};
for (const row of animalSubjectRows) {
  if (row.length >= 2) subjectMap[row[0]] = nullify(row[1]);
}
console.log(`  ${Object.keys(subjectMap).length} subjects`);

// 2. document_subjects  →  document_id → [subject_names]
console.log('Parsing document_subjects...');
const dsStart = findCopyStart(lines, 'document_subjects');
const docSubjectRows = parseCopyBlock(lines, dsStart);
const docSubjectMap = {};
for (const row of docSubjectRows) {
  if (row.length < 2) continue;
  const docId = row[0];
  const subName = subjectMap[row[1]];
  if (!docSubjectMap[docId]) docSubjectMap[docId] = [];
  if (subName) docSubjectMap[docId].push(subName);
}
console.log(`  ${Object.keys(docSubjectMap).length} bills have subjects`);

// 3. bill_actions  →  document_id → [{ date, text, source }]
// Columns: id(0), document_id(1), action_code(2), action_date(3), text(4),
//          action_type(5), source_system_code(6), source_system_name(7), ingested_at(8)
console.log('Parsing bill_actions...');
const baStart = findCopyStart(lines, 'bill_actions');
const billActionRows = parseCopyBlock(lines, baStart);
const billActionsMap = {};
for (const row of billActionRows) {
  if (row.length < 8) continue;
  const docId = row[1];
  if (!billActionsMap[docId]) billActionsMap[docId] = [];
  billActionsMap[docId].push({
    date: nullify(row[3]),
    text: nullify(row[4]),
    source: nullify(row[7]),
    action_type: nullify(row[5]),
  });
}
// Sort each bill's actions newest-first
for (const docId in billActionsMap) {
  billActionsMap[docId].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
}
console.log(`  ${billActionRows.length} actions across ${Object.keys(billActionsMap).length} bills`);

// 4. legislative_documents
// Columns: id(0), source(1), source_id(2), source_url(3), congress(4), bill_type(5),
//          bill_number(6), title(7), introduced_date(8), origin_chamber(9), policy_area(10),
//          last_action_date(11), last_action_text(12), update_date(13), update_date_incl_text(14),
//          source_hash(15), api_raw(16), ingested_at(17), updated_at(18)
console.log('Parsing legislative_documents...');
const ldStart = findCopyStart(lines, 'legislative_documents');
const ldRows = parseCopyBlock(lines, ldStart);
console.log(`  ${ldRows.length} bills found`);

const bills = [];
for (const row of ldRows) {
  if (row.length < 13) continue;

  const id           = row[0];
  const sourceId     = nullify(row[2]);
  const sourceUrl    = nullify(row[3]);
  const congress     = nullify(row[4]);
  const billType     = nullify(row[5]);
  const billNumber   = nullify(row[6]);
  const title        = nullify(row[7]);
  const introducedDate = nullify(row[8]);
  const originChamber  = nullify(row[9]);
  const policyArea     = nullify(row[10]);
  const lastActionDate = nullify(row[11]);
  const lastActionText = nullify(row[12]);

  // Derive current_stage from last action text
  let currentStage = 'Referred to Committee';
  const lat = (lastActionText || '').toLowerCase();
  if (lat.includes('signed by president') || lat.includes('became public law')) currentStage = 'Signed into Law';
  else if (lat.includes('passed senate') || lat.includes('agreed to in senate')) currentStage = 'Passed Senate';
  else if (lat.includes('passed house') || lat.includes('agreed to in house')) currentStage = 'Passed House';
  else if (lat.includes('rules committee')) currentStage = 'Rules Committee';
  else if (lat.includes('senate legislative calendar')) currentStage = 'On Senate Calendar';
  else if (lat.includes('union calendar')) currentStage = 'On House Calendar';
  else if (lat.includes('received in the senate')) currentStage = 'In Senate';
  else if (lat.includes('reported') && lat.includes('amended')) currentStage = 'Reported from Committee';
  else if (lat.includes('subcommittee hearings held')) currentStage = 'Subcommittee Hearing';
  else if (lat.includes('forwarded by subcommittee')) currentStage = 'Forwarded by Subcommittee';
  else if (lat.includes('referred to')) currentStage = 'Referred to Committee';
  else if (lat.includes('introduced')) currentStage = 'Introduced';

  // Extract sponsor from api_raw
  const apiRaw = row.length > 16 ? (row[16] || '') : '';
  const { sponsor_name, sponsor_party, sponsor_state } = extractSponsor(apiRaw);

  const subjects = docSubjectMap[id] || [];
  const action_history = billActionsMap[id] || [];

  bills.push({
    id,
    source_id: sourceId,
    source_url: sourceUrl,
    congress: parseInt(congress) || 119,
    bill_type: billType,
    bill_number: billNumber,
    title,
    introduced_date: introducedDate,
    origin_chamber: originChamber,
    policy_area: policyArea,
    last_action_date: lastActionDate,   // YYYY-MM-DD
    last_action_text: lastActionText,
    current_stage: currentStage,
    sponsor_name,
    sponsor_party,
    sponsor_state,
    subjects,
    action_history,
  });
}

// Compute derived stats
const uniqueSubjectSet = new Set(bills.flatMap(b => b.subjects));
const UNIQUE_SUBJECTS = uniqueSubjectSet.size;
const TOTAL_BILLS = bills.length;

// Build all unique action dates (for the date picker)
const allActionDates = new Set();
for (const b of bills) {
  for (const a of b.action_history) {
    if (a.date) allActionDates.add(a.date);
  }
}
const ACTION_DATES = [...allActionDates].sort();

const output = `// AUTO-GENERATED — do not edit manually
// Source: local_backup_2026_06_04.sql
// Regenerate: node scripts/parseSqlDump.js

export const BILLS = ${JSON.stringify(bills, null, 2)};

export const TOTAL_BILLS = ${TOTAL_BILLS};
export const UNIQUE_SUBJECTS = ${UNIQUE_SUBJECTS};
export const ACTION_DATES = ${JSON.stringify(ACTION_DATES)};
`;

fs.mkdirSync(path.dirname(OUTPUT_FILE), { recursive: true });
fs.writeFileSync(OUTPUT_FILE, output, 'utf-8');

console.log('\n✅ Done!');
console.log(`   Bills    : ${TOTAL_BILLS}`);
console.log(`   Subjects : ${UNIQUE_SUBJECTS} unique`);
console.log(`   Dates    : ${ACTION_DATES.length} unique action dates`);
console.log(`   Output   : ${OUTPUT_FILE}`);
