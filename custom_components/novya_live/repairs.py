"""Repair flows for Novya.live."""

from __future__ import annotations

from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.core import HomeAssistant


class RestartRequiredRepairFlow(ConfirmRepairFlow):
    """Confirm flow that restarts Home Assistant to apply a pending update."""

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Restart Home Assistant once the user confirms."""
        if user_input is not None:
            await self.hass.services.async_call(
                "homeassistant", "restart", blocking=False
            )
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow for the given issue."""
    return RestartRequiredRepairFlow()
