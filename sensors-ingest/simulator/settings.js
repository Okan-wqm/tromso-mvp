// Node-RED settings for the field simulator (development only; the editor is published on 127.0.0.1 alone).
module.exports = {
  flowFile: 'flows.json',
  // The credentials file is written from the environment at start (start.sh); nothing to encrypt or keep.
  credentialSecret: false,
  uiPort: 1880,
  flowFilePretty: true,
  logging: { console: { level: 'info', metrics: false, audit: false } },
  editorTheme: { projects: { enabled: false }, tours: false },
  externalModules: { autoInstall: false, palette: { allowInstall: false } },
};
