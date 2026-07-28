# Adding a new county format (developer note)

The system is a plug-in registry, so new formats are added without touching the
rest of the pipeline.

1. **Create** `app/parsers/<newformat>.py` exposing three things:
   ```python
   NAME = "Human readable format name"

   def detect(folder, files) -> bool:
       # cheap fingerprint: filenames present, or header columns of one file
       ...

   def parse(folder, files) -> pandas.DataFrame:
       # return rows using the STANDARD_COLUMNS names from app/config.py
       # (missing columns are fine; finalize_standard fills blanks)
       ...
   ```

2. **Register** it in `app/detect.py` `PARSERS = [...]`, placed *before* the
   `generic` fallback and ordered by specificity (most specific first).

3. **Normalize**: the parser only needs to produce the standard column names
   (see `config.STANDARD_COLUMNS`). The central `vacant_filter` and the matcher
   handle the rest. Set `Vacant = "Y"` if the source is already vacant-only;
   otherwise leave it and the land-use text decides.

4. **Test**: drop a real sample into `Input/<County>/` and run
   `python -m app.main`. Check the run report and the Vacant Land CSV.

Detection contract: `detect()` must return `False` when unsure. It is better to
let a county fall through to the clear "UNRECOGNIZED — needs mapping" report than
to guess and emit wrong data.
