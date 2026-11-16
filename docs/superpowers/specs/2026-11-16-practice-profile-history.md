# Practice Profile History

## Goal

Let a signed-in employee reuse previously entered practice customer profiles from the practice setup page.

## Behavior

- Add a blue “历史填写” button immediately to the left of the existing return-to-module button.
- Open an inline history list; each row shows the training mode, organization/target, and saved time, with a one-click “一键使用” action.
- Selecting an entry restores all profile fields and its training mode.
- Save a profile only after practice session preparation succeeds.
- Store records in browser localStorage, namespaced by authenticated user ID, keeping the latest 20.
- If localStorage is unavailable or malformed, practice setup continues and the history list is empty.

## Scope

This is browser-local history. It is not synchronized across browsers or devices. No backend or database changes are needed.
