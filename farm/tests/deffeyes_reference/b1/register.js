// Resolves the engine's two package imports to the harness's copies without editing any copied file (driver.ts).
const Module = require('module');
const path = require('path');
const ALIASES = {
  '@aquaculture/shared-contracts': path.join(__dirname, 'stubs', 'shared-contracts.js'),
  '@platform/aquaculture-engines': path.join(__dirname, 'src', 'libs', 'aquaculture-engines', 'src', 'water-chemistry', 'index.js'),
};
const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  return resolve.call(this, ALIASES[request] || request, ...rest);
};
