# MGL OCM — Full System Foundation

This build is based on the uploaded Django project. It keeps the existing apps and FC26 player database (your uploaded `fc26_players_mgl.csv` is based on FIFA/EA FC 26 data even though the converted column is named `fc27_id`), then adds a central MGL competition/reward/approval layer and a Discord outbox bot.

## Economy
- Managers start with 50.00 tokens.
- Approved league match: +1.00 to both managers.
- Approved TOTW player: +0.20 to that player's manager.
- Manager of the Week: +0.50.
- Approved post-match press conference: +0.20.
- Elite pack costs 20.00 tokens.
- Manager tokens use DecimalField so 0.20/0.50 rewards are exact.

## Player ownership
All imported FC26 players stay free agents until an approved auction/pack/assignment gives them to an MGL team. Squad limit is 30. A manager release is immediate and sends the player back to free agents; it does not require approval.

## TOTW
Use 4-2-3-1. For selection logic, treat CM/CDM as the central-midfield pool and RW/RM + LW/LM as the corresponding wide pools. When a LW wins the wide-left slot display it as LM; an actual LM remains LM. A future TOTW scoring service can calculate the XI from approved match data only.

## Admin approval
Competitive results and rewards are only finalized by Admin/Owner. The existing Django admin is the approval control point; the website should never publish a pending result as official.

## Discord
The website is the source of truth. Approved events become `NewsPost` rows. `discord_bot.bot` polls those rows and posts them to mapped Discord channels. Configure `DISCORD_TOKEN` and `MGL_CHANNELS`.

## First run
1. Activate the venv.
2. `pip install -r requirements-mgl.txt`
3. `python manage.py makemigrations`
4. `python manage.py migrate`
5. `python manage.py seed_packs`
6. `python manage.py mgl_reset` if you want a completely blank competition setup while keeping the player database.
7. Create leagues/teams in Admin. Only Owner/Admin should edit team name/logo/manager assignment.
8. Keep FC26 players as free agents until you deliberately allocate them.
