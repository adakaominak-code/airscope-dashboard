# AirScope — free hosted dashboard

Deploy this folder to Streamlit Community Cloud using `cloud_app.py` as the entry point and Python 3.13 or 3.14. Install the pinned `requirements.txt` dependencies. No database secrets or XAMPP server are required online.

The complete read-only snapshot contains 1,121,444 air readings, 29,383 city-day AQI rows, 405,213 explicitly simulated admissions, 26 cities, 21 states, and every other base table from the local project database. Dates cover 2015-01-01 through 2026-11-05, with different coverage by city and source. The manifest records counts and a SHA-256 checksum.

`cloud_app.py` extracts the compressed database into temporary server storage and verifies it before use. Restarting or waking the app reconstructs the same data. SQLite runs dashboard queries locally on the host; it never connects to the owner's computer. The original MariaDB stored routines and triggers remain part of the local DBMS project; the online copy contains their calculated results, not executable MariaDB routines.

## Publish

1. Upload only this folder to a new GitHub repository. `.env`, database passwords, local archives, and the uncompressed `.sqlite` file must stay excluded.
2. Sign in at https://share.streamlit.io/ using GitHub.
3. Create an app from the repository, branch `main`, entry point `cloud_app.py`.
4. Select Python 3.13 or 3.14 and deploy. Set app sharing to public so viewers do not need an invitation.
5. Verify the resulting `.streamlit.app` address in a signed-out browser before sharing.

Free Community Cloud apps sleep after inactivity. A viewer can wake the app; the owner's computer is not needed. Free hosting has resource and availability limits.

## Update the data

This is a snapshot, not automatic synchronization. Run the exporter from the original XAMPP project after updating the source database, verify counts/query parity again, and publish the new compressed database and manifest together. Never edit the hosted SQLite copy manually.

This folder is prepared for deployment; its existence alone does not mean the app is published.
