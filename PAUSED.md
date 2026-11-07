# chemcore: paused (coordinator, 2026-11-07)

Last commit: S5 step 2, the switch of deffeyes.py's analysis to the core. Image: balik-testrunner-chemcore:s5
(EXPECTED core_hash 8093e9643f11451f). No test container is running.

Next, in order:
1. Run the FULL Django suite on HEAD in balik-testrunner-chemcore:s5 (the S4 and S5 switches were verified on farm
   (1047 tests, S4) and on the chemistry tests (188, S5) only; the shared database was too loaded for the rest).
   Fix anything it shows, test first. Also run chemcore/scripts/test.sh (chemcore-tools:s1), makemigrations --check,
   data_map --check, compile_catalogs, npx tsc, npm test.
2. README: S5 done in the step table (and the floor tie noted: 10 degC, S 0, pH 9, an alkalinity one ulp above
   Python's floor flips; listed by test_native_analysis).
3. Merge main (wip/sensors landed at b24de24; main is later): rebuild the image, regenerate EXPECTED and the guard
   list, rerun the suite; record golden for figure/render/frames as a new block (v1 stays).
4. S6 geometry and figure (codes and numbers, messages.py, test_deffeyes_figure.py rewritten first), S7 dosing,
   simulator, calculate, plots, S8 scene, S9 replay batch and binary encoding (measure on the dev DB's real sensor
   readings, read only), S10 retirement audit. Then I2 (golden v3 beside v1, owner sees it first).
Delete this file when resuming.
