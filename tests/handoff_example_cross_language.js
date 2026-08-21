// The committed handoff example must be reproducible by a JavaScript implementation.
//
// The example exists so the AeroSelect side can assert byte-equality against it. That promise was
// false when it shipped: the payload carried 810.0 and 1000.0, and JavaScript cannot emit a
// trailing .0 at all — Python writes 810.0, JSON.stringify writes 810. Their hashes differed for a
// document that was otherwise perfectly correct, so the first thing the exporter's author would
// have seen is a failure with no bug behind it, and the obvious "fix" would have been to bend the
// TypeScript canonicaliser until it matched — breaking the live path that works.
//
// This runs the exact recipe published in docs/AEROSELECT-HANDOFF.md, so the doc and the fixture
// are checked against each other rather than each being trusted on its own.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const file = path.join(__dirname, '..', 'docs', 'examples', 'aeroselect-selection-example.json');
const doc = JSON.parse(fs.readFileSync(file, 'utf8'));

// Recursive key sort. Arrays keep their ORDER — payload.sections is in airflow order, and a
// canonicaliser that sorted array elements would silently reorder a unit's module chain and still
// hash "successfully".
const canonical = (v) =>
  Array.isArray(v) ? v.map(canonical)
  : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canonical(v[k])]))
    : v;

const env = doc.aeroselect;
const attested = {
  envelope: {
    document: env.document,
    specVersion: env.specVersion,
    selectionRef: env.selectionRef,
    engine: env.engine,
    engineVersion: env.engineVersion,
    generatedOn: env.generatedOn,
  },
  payload: doc.payload,
};

const bytes = Buffer.from(JSON.stringify(canonical(attested)), 'utf8');
const computed = 'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex');

if (computed !== env.contentHash) {
  console.error('The committed example cannot be reproduced from JavaScript.\n');
  console.error('  declared : ' + env.contentHash);
  console.error('  computed : ' + computed + '\n');
  console.error('Most likely a whole-number float somewhere in the payload: Python renders 810.0,');
  console.error('JavaScript renders 810, and the bytes differ. Regenerate with');
  console.error('tools/make_selection_example.py, which now refuses to write one.');
  process.exit(1);
}

// And the array-order rule, asserted rather than only documented.
const sections = doc.payload.sections || [];
if (sections.length > 1) {
  const sorted = [...sections].map((s) => s.type).sort();
  const actual = sections.map((s) => s.type);
  if (JSON.stringify(sorted) === JSON.stringify(actual)) {
    console.error('The example\'s sections happen to be in alphabetical order, so this file cannot');
    console.error('detect a canonicaliser that wrongly sorts arrays. Reorder them.');
    process.exit(1);
  }
}

console.log('handoff example: reproducible from JavaScript (' + computed.slice(0, 22) + '…),');
console.log('  ' + sections.length + ' sections in a non-alphabetical order, so array-order errors are detectable.');
