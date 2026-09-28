# IBM Bob integration boundary

IBM Bob is the reasoning/orchestration layer in the intended hackathon deployment.

## Runtime boundary
`app/bob.py` is the single integration point.

The application sends:
```json
{
  "mode": "hypothesis-assessor",
  "input": {
    "case_id": "...",
    "evidence_id": "...",
    "original_hash": "...",
    "observations": []
  }
}
```

Configure the actual Bob gateway using:
```text
BOB_MODE=http
BOB_BASE_URL=<gateway supplied by IBM/hackathon>
BOB_API_KEY=<secret>
BOB_MODEL=<model supplied by IBM/hackathon>
```

The code does not hard-code an undocumented endpoint or pretend that a local Bob SDK is available.

## Bob modes
- `hypothesis-assessor`
- `skeptic`
- `adversarial`
- `legal-proposer`
- `brief`

## Principle
Deterministic tools produce observations. Bob reasons over observations. The investigator reviews. The report compiler preserves the complete trace.
