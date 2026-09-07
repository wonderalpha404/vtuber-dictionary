# Processor interface

Processors consume normalized JSON documents from `work/<processor>/input/` and produce the same document format in `ok`, `ng`, or `error`.

The runner is invoked with a processor name and a record count. It collects records across input files until the requested count is reached or input is exhausted.

Shared code handles JSON I/O, input collection, result classification, `previous_processor`, logs, and batch commit handling. Processor implementations provide only processor-specific behavior.

`pipeline/pipeline.json` is a human-readable flow memo. Executable code does not read it.
