# TODO

## Advanced engine controls

- [ ] Expose queue limits: `--max-pending` and `--max-pending-per-client`, including zero to disable queuing.
- [ ] Expose request timeout: `--request-timeout-ms` (waiting time included).
- [ ] Expose stall timeout: `--stall-timeout-ms` (off by default; minimum 60000 ms when enabled). Explain that it exits the engine when generation stalls.
- [ ] Expose connection limits: `--max-connections`.
- [ ] Consider request-body and response-size limits: `--max-request-bytes` and `--max-output-bytes`.

Keep these in More options, validate against upstream limits, preserve existing preset behavior, and cover command generation and form restoration.

## Future scope

- [ ] Evaluate launch support for other Gufo modalities separately from the text-server GUI.
