"""Handling fish: what to know before harvesting, transporting, grading or treating them.

- `withdrawal.py`: the medicine-withdrawal registry. The health records register their provider; with none
  registered the check says "withdrawal not checked".
- `fasting.py`: the fasting rules (HandlingRule), when the fish were last fed, and the fasts a planned
  harvest or transport asks for (`fasting_on`, for the meal board).
- `check.py`: the one handling check (`check`, `assess`) the harvest, transfer, grading and treatment dialogs
  and the save itself call, and the acknowledgement written when a person goes on past its warnings.

Nothing here blocks anything (owner decision): a withdrawal in force and too short a fast are warnings;
going on stores a HandlingAcknowledgement per warning and the operation's log entry is critical."""
