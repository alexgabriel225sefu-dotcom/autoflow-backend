# Rule field enforcement

These fields are visible in RuleDoc terms and must either be enforced by the runtime or refused before activation. A client must never see a risk or execution control accepted when the engine will ignore it.

| Field | Decision | Why |
| --- | --- | --- |
| `takeProfit` | Validate and allow `rr` or `pips`. | The execution bridge already converts it into the order target price. Validation now refuses missing or non-positive target values before activation. |
| `schedule` | Validate and allow UTC trading days and time windows. | The evaluator already blocks new entries outside the configured schedule. Validation now refuses unsupported timezones, invalid weekdays and malformed windows before activation. |
| `trailingStop` | Refuse when `enabled` is true. | No platform runtime path trails broker stops yet. Accepting this setting would make the Rule terms screen promise a control that is not executed. |
| `breakEven` | Refuse when `enabled` is true. | No platform runtime path moves stops to breakeven yet. Accepting this setting would make the Rule terms screen promise a control that is not executed. |
