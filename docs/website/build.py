#!/usr/bin/env python3
"""Build the AgriPulse documentation site (simulation).

All page content lives in this file. Running it writes plain, standalone HTML
pages next to it, sharing assets/site.css and img/*.jpg.

    python docs/website/build.py

Counts and names come from the repository seed files: 23 crops, 12 imagery
indices, 6 weather derived signals, 9 weather indices, 18 decision trees,
9 scouting signal definitions and 5 forms, 6 mango cultivar plan templates,
7 date palm cultivar plan templates.
"""

from __future__ import annotations

import html
import os

HERE = os.path.dirname(os.path.abspath(__file__))


# ===========================================================================
# Shared content
# ===========================================================================

PILLARS = [
    ("Observe", "Satellite optical and thermal imagery, daily weather, and what your"
                " scouts record in the field, all keyed to the same farm and block shapes."),
    ("Interpret", "Vegetation, water and heat indices per block and per grid cell, compared"
                  " against the baseline for that block at that time of year."),
    ("Act", "Decision trees open recommendations and alerts. Your team assigns them,"
            " dispatches them to a worker or a scout, and closes them with an outcome."),
]

LOOP = [
    ("Subscribe", "A farm is connected to an imagery provider and to weather. Blocks inherit it."),
    ("Acquire", "Passes are found and fetched. Weather is pulled every day, history and forecast."),
    ("Compute", "Indices per pass, per block and per grid cell. Weather signals per day."),
    ("Evaluate", "Decision trees read the numbers, the crop stage and the field signals, and record why."),
    ("Act", "Recommendations and alerts open, get assigned, get dispatched, and get closed."),
]

STATS = [
    ("23", "crops seeded"),
    ("12", "imagery indices"),
    ("18", "decision trees"),
    ("15", "weather signals"),
    ("2", "languages"),
]

SUPPORT = [
    ("faq", "❓", "FAQs", "The questions we answer most often, grouped by process.", "To be designed"),
    ("ask", "💬", "Ask the AgriPulse team", "Send a question to the people who build and run the platform.", "To be designed"),
    ("feature", "✨", "Request a feature", "Tell us what is missing. Requests are read and answered.", "To be designed"),
]


# ===========================================================================
# Processes
# ===========================================================================

PROCESSES = [
    {
        "slug": "process-map-the-farm",
        "num": "01",
        "img": "p01-map",
        "title": "Map the farm",
        "tile": "From an empty account to a farm with a boundary, blocks, a grid and the right "
                "people attached.",
        "lede": "Everything else hangs off the farm shape. This process takes you from an empty "
                "account to a farm with a boundary, blocks, a grid, land units and a named person "
                "on each block.",
        "who": "Tenant admin, farm manager",
        "time": "30 to 90 minutes for one farm",
        "clip": "9 minutes",
        "start": [
            "A tenant account and an admin sign-in.",
            "The farm boundary: a map you can trace, or a file to upload.",
            "A list of the blocks you manage, with the names you already use in the field.",
        ],
        "stages": [
            {
                "t": "Create the farm",
                "where": "Farm management → New farm",
                "guide": ("guide-create-a-farm", "Full guide: create a farm"),
                "steps": [
                    "Give the farm a name your team already uses.",
                    "Set the country. It drives the region targeting used by decision trees.",
                    "Draw the boundary on the map, or upload it.",
                    "Save. The farm now appears in the farm picker at the top of the workspace.",
                ],
            },
            {
                "t": "Add the blocks",
                "where": "Farm management → Blocks",
                "steps": [
                    "Draw each block, or upload a file with the block shapes.",
                    "For a regular field, use auto-grid to cut the farm into equal blocks.",
                    "Give each block a code that matches the sign on the gate.",
                    "Check the area figure against what you know. A wrong area means a wrong shape.",
                ],
                "note": "Blocks may not overlap. If two blocks share ground, every per-block "
                        "number is counted twice.",
            },
            {
                "t": "Set the grid cell size",
                "where": "Farm management → Farm tab → Grid template",
                "steps": [
                    "Choose the cell size for the whole farm. Cell size is a farm setting, not a block setting.",
                    "A smaller cell shows more variation inside a block and costs more to compute.",
                    "Save, then wait for the grid to build before you open the map.",
                ],
            },
            {
                "t": "Mark the land units",
                "where": "Farm management → Land units",
                "steps": [
                    "Draw roads, buildings, canals and any other area that is not crop.",
                    "Land units are excluded from crop numbers, so index averages stop being dragged down.",
                ],
            },
            {
                "t": "Attach the people",
                "where": "Farm management → Members, and the block detail page",
                "steps": [
                    "Invite the users who work on this farm and give each one a role.",
                    "Limit a member to named farms if they should not see the rest.",
                    "Set the responsible agronomist on each block. Work opened on that block goes to them.",
                ],
            },
        ],
        "check": [
            "The farm picker shows the farm, and the map shows the boundary you drew.",
            "The sum of block areas is close to the farm area, minus the land units.",
            "Opening the Farm Console shows the grid drawn inside each block.",
        ],
        "related": [("concepts", "Key concepts"), ("kb", "Knowledge Base")],
    },
    {
        "slug": "process-plan-the-season",
        "num": "02",
        "img": "p02-season",
        "title": "Plan the season",
        "tile": "Put a crop on every block, record how it was established, and build the season "
                "calendar from a template.",
        "lede": "A block with no crop is a block the platform cannot reason about. This process "
                "assigns the crop, records how it was planted, and turns a plan template into a "
                "working season calendar.",
        "who": "Farm manager, agronomist",
        "time": "One afternoon for a farm, then a few minutes per block",
        "clip": "11 minutes",
        "start": [
            "A mapped farm with blocks. See Map the farm.",
            "The crop and variety on each block, and the planting or transplant date.",
        ],
        "stages": [
            {
                "t": "Assign the crop",
                "where": "Farm management → Block → Crop",
                "steps": [
                    "Pick the crop from the seeded catalog of 23 crops.",
                    "Pick the variety where one exists, for example mango Sukkary.",
                    "Set the planting date, and the end date if the block changes crop during the year.",
                    "For many blocks at once, use bulk assignment.",
                ],
                "note": "The crop path, for example mango.sukkary, is what a decision tree matches "
                        "on. A tree written for mango runs on every mango block. A tree written "
                        "for mango.sukkary runs only on that variety.",
            },
            {
                "t": "Record how the block was established",
                "where": "Farm management → Block → Attributes",
                "steps": [
                    "Fill the crop attributes that ship with the crop, for example rootstock type, "
                    "offshoot age, or seed tuber grade.",
                    "These are the same fields for every tenant, so the numbers can be compared later.",
                    "Decision trees can read these fields as a condition.",
                ],
            },
            {
                "t": "Start from a plan template",
                "where": "Plan → New season plan",
                "steps": [
                    "Pick the plan template for the crop or the cultivar.",
                    "Set the season start date. The template dates shift to match.",
                    "Delete the activities you do not do, and add your own.",
                ],
            },
            {
                "t": "Build the calendar",
                "where": "Plan board",
                "steps": [
                    "Move an activity to the week you will actually do it.",
                    "Attach the worker or the machine that will do it.",
                    "Mark an activity done when the work is finished.",
                ],
            },
            {
                "t": "Add the roster",
                "where": "Settings → Resources",
                "steps": [
                    "Add the people and machines that work on this farm.",
                    "A resource can then receive dispatched work from the Action Center.",
                ],
            },
        ],
        "check": [
            "Every block shows a crop and a planting date.",
            "The Plan board shows activities on the weeks you expect.",
            "Opening a block shows the crop stage the phenology model puts it in today.",
        ],
        "related": [("kb-crop-mango", "Mango"), ("kb-plans", "Plan templates"),
                    ("kb-attributes", "Crop attributes")],
    },
    {
        "slug": "process-connect-the-data",
        "num": "03",
        "img": "p03-connect",
        "title": "Connect the data",
        "tile": "Subscribe the farm to satellite imagery and weather, choose the indices, and "
                "backfill the history.",
        "lede": "Nothing is computed until a farm is subscribed. This process turns on imagery "
                "and weather for a farm, picks the indices, and pulls back the history you need "
                "for a baseline.",
        "who": "Tenant admin, platform admin",
        "time": "15 minutes to set up, hours to days for the backfill",
        "clip": "8 minutes",
        "start": [
            "A mapped farm. Subscriptions are set at farm level, not block level.",
            "A decision on how far back you need history.",
        ],
        "stages": [
            {
                "t": "Subscribe the farm to imagery",
                "where": "Settings → Imagery and weather → Farm",
                "steps": [
                    "Pick the provider and the product.",
                    "Turn on fetching for the whole farm area.",
                    "Set the cloud limit you accept for a pass.",
                ],
                "note": "A cloud limit applied at the provider means rejected passes never arrive "
                        "at all. If every stored pass reads exactly 0.0 percent cloud, the limit "
                        "is filtering at the source.",
            },
            {
                "t": "Choose the indices",
                "where": "Settings → Imagery and weather → Indices",
                "steps": [
                    "Turn on the indices you will read. NDVI is the usual starting point.",
                    "Add NDRE for tree crops, NDMI or MSI for canopy moisture, BSI for bare soil.",
                    "Each index you add costs computation on every pass.",
                ],
            },
            {
                "t": "Add thermal, if you need it",
                "where": "Settings → Imagery and weather → Thermal",
                "steps": [
                    "Thermal comes from a different satellite, with a coarser pixel and a longer "
                    "gap between passes.",
                    "It gives land surface temperature, crop water stress and a soil moisture index.",
                    "Thermal has no grid cells. It is read at block and farm level only.",
                ],
            },
            {
                "t": "Subscribe to weather",
                "where": "Settings → Imagery and weather → Weather",
                "steps": [
                    "Turn on weather for the farm. History and forecast come from the same provider.",
                    "Set how many days of forecast you want to see.",
                    "The daily job computes growing degree days, reference evapotranspiration and "
                    "cumulative rainfall.",
                ],
            },
            {
                "t": "Backfill the history",
                "where": "Platform → Backfill",
                "steps": [
                    "Start a backfill for the farm and the date range.",
                    "Watch the run. A backfill of several years takes hours.",
                    "Baselines need history. Without it, an anomaly cannot be called.",
                ],
            },
            {
                "t": "Check what arrived",
                "where": "Farm Console → scene strip, and Platform → Integrations health",
                "steps": [
                    "Read the scene strip. It shows one mark per pass day.",
                    "Open a pass and check the coverage and the cloud figure.",
                    "If passes stop arriving, integration health names the failing step.",
                ],
            },
        ],
        "check": [
            "The scene strip shows passes on the dates you expect.",
            "The index chart on Insights draws a line, not an empty panel.",
            "The weather panel shows yesterday and the forecast days ahead.",
        ],
        "related": [("kb-indices", "Imagery index catalog"), ("kb-weather", "Weather catalog")],
    },
    {
        "slug": "process-read-the-field",
        "num": "04",
        "img": "p04-read",
        "title": "Read the field",
        "tile": "Find where the crop is under stress: from the farm number, to the block, to the "
                "single grid cell.",
        "lede": "This is the daily job. Start at the farm, find the block that moved, then find "
                "the part of the block that moved. Every step narrows the area you have to walk.",
        "who": "Farm manager, agronomist",
        "time": "10 minutes a day",
        "clip": "12 minutes",
        "start": [
            "A farm with imagery and weather connected. See Connect the data.",
            "Enough history for a baseline, ideally more than one season.",
        ],
        "stages": [
            {
                "t": "Start on Insights",
                "where": "Insights",
                "steps": [
                    "Read the KPI row: it counts what is open on this farm, not the whole account.",
                    "Set the time range. A short range shows the last few passes, a long range shows the season.",
                    "Read the index chart. Each point is one pass, not one day.",
                ],
            },
            {
                "t": "Compare against the baseline",
                "where": "Insights → index chart",
                "steps": [
                    "The baseline is what this block usually reads at this time of year.",
                    "A value below the baseline band is what makes an anomaly, not a low number on its own.",
                    "Forecast days are excluded from the baseline and from the summary figures.",
                ],
            },
            {
                "t": "Open the map",
                "where": "Farm Console",
                "steps": [
                    "Switch the map to the index and the pass date you want.",
                    "Colour is drawn per pixel inside the farm boundary, and per cell inside a block.",
                    "Blocks that moved against their own history stand out first.",
                ],
            },
            {
                "t": "Inspect one cell",
                "where": "Farm Console → cell inspector",
                "steps": [
                    "Click a cell to see its value on this pass and its history.",
                    "A single low cell is usually an irrigation fault, a gap in the stand, or a road.",
                    "If the cell is a road, add it as a land unit so it stops counting.",
                ],
            },
            {
                "t": "Read the weather beside it",
                "where": "Insights → Weather",
                "steps": [
                    "Check rainfall against evapotranspiration for the same days.",
                    "A drop in the vegetation index after a hot dry week reads differently from a "
                    "drop after a cool wet one.",
                    "The forecast days are marked so you do not read them as measurements.",
                ],
            },
            {
                "t": "Read what the field said",
                "where": "Farm Console → block signals",
                "steps": [
                    "Scout observations sit on the same block, on their own dates.",
                    "A canopy vigour of poor recorded on the ground confirms what the index showed.",
                ],
            },
        ],
        "check": [
            "You can name the block that changed and the date it changed.",
            "You can say whether the weather explains it.",
            "You know which part of the block to walk.",
        ],
        "related": [("kb-indices", "Imagery index catalog"), ("kb-weather", "Weather catalog"),
                    ("concepts", "Key concepts")],
    },
    {
        "slug": "process-author-the-agronomy",
        "num": "05",
        "img": "p05-agronomy",
        "title": "Write the agronomy",
        "tile": "Turn a rule your agronomist keeps in their head into a decision tree that runs "
                "on every block, every pass.",
        "lede": "A decision tree is the rule your agronomist already applies, written down once "
                "and run on every block. This process goes from a seeded tree to a published "
                "version of your own, with a dry run before anything opens.",
        "who": "Agronomist, tenant admin",
        "time": "An hour for a first tree",
        "clip": "16 minutes",
        "start": [
            "A farm with data flowing, so a dry run has something to read.",
            "The rule itself, in words, with the numbers you use today.",
        ],
        "stages": [
            {
                "t": "Start from something that works",
                "where": "Decision trees → Library",
                "steps": [
                    "Read the 18 seeded trees first. One may already say what you mean.",
                    "Copy a seeded tree instead of starting from an empty canvas.",
                    "Set the crop path so the tree runs on the right blocks.",
                ],
            },
            {
                "t": "Lay out the nodes",
                "where": "Decision trees → Editor canvas",
                "steps": [
                    "A tree is a flow of nodes. A decision node branches on match or miss.",
                    "Add the nodes, then rewire the branches by dragging the connector.",
                    "The editor loads the draft. Publish is a separate step.",
                ],
            },
            {
                "t": "Write the conditions",
                "where": "Node details → Condition builder",
                "steps": [
                    "Pick the source: an imagery index, a weather value, a field signal, the crop "
                    "stage, or a block attribute.",
                    "Pick the operator and the threshold.",
                    "Combine terms with all or any.",
                ],
            },
            {
                "t": "Declare the thresholds as parameters",
                "where": "Tree → Parameters",
                "steps": [
                    "Give each number a name and a default, for example warn_score with default 40.",
                    "A tenant can then change the number without editing the tree.",
                    "This is how one tree serves farms in different districts.",
                ],
            },
            {
                "t": "Dry run before you publish",
                "where": "Tree → Dry run",
                "steps": [
                    "Run the draft against real data for a chosen farm and date.",
                    "Read how many blocks matched. Nothing is opened by a dry run.",
                    "If it matches every block, the threshold is too loose.",
                ],
            },
            {
                "t": "Publish the version",
                "where": "Tree → Publish",
                "steps": [
                    "Publishing makes this version the one that runs.",
                    "The old version stays in the history, so you can go back.",
                    "From here the tree runs on schedule, on every pass.",
                ],
            },
            {
                "t": "Read the trace when nothing fires",
                "where": "Tree → Evaluation trace",
                "steps": [
                    "The trace records every block the tree looked at and why it stopped.",
                    "Most often the data was missing, not the rule wrong.",
                    "You can also run a tree on a farm on demand instead of waiting for the schedule.",
                ],
                "note": "Re-running a tree opens nothing new for a block that already has an open "
                        "item for the same rule. A run that reports zero opened is not a failure.",
            },
        ],
        "check": [
            "The dry run matched the blocks you expected, and not the rest.",
            "The published version shows in the tree history with today's date.",
            "After the next pass, the trace shows the tree ran.",
        ],
        "related": [("kb-trees", "Decision tree library"), ("kb-signals", "Scouting signal catalog"),
                    ("kb-indices", "Imagery index catalog")],
    },
    {
        "slug": "process-run-the-field-team",
        "num": "06",
        "img": "p06-team",
        "title": "Run the field team",
        "tile": "Send scouts to the right block, collect what they see on a phone, and feed it "
                "back into the rules.",
        "lede": "Satellites see the canopy. They do not see the insect under the leaf. This "
                "process sets up the forms, puts them on a phone, and brings the answers back "
                "where the decision trees can read them.",
        "who": "Agronomist, farm manager, scout",
        "time": "A day to set up, then daily use",
        "clip": "13 minutes",
        "start": [
            "A mapped farm with blocks.",
            "Phones for the scouts, and a phone number for each scout.",
        ],
        "stages": [
            {
                "t": "Read the forms that ship with the app",
                "where": "Settings → Custom signals",
                "steps": [
                    "Nine signal definitions and five forms are seeded for every tenant.",
                    "They cover canopy vigour, pest incidence, disease severity and symptom, weed "
                    "pressure, soil moisture by feel, observed cause of stress, irrigation faults "
                    "and photographs.",
                    "Use them before writing your own, so numbers stay comparable between farms.",
                ],
            },
            {
                "t": "Add a signal of your own",
                "where": "Settings → Custom signals → New",
                "steps": [
                    "Pick the value kind: a number, a category, or an event.",
                    "Pick how repeated readings combine: mean, max, min, sum, count or latest.",
                    "Only numbers can use mean, max, min or sum. Anything else falls back to latest.",
                ],
            },
            {
                "t": "Enrol the scouts",
                "where": "Settings → Users",
                "steps": [
                    "Create the scout with their phone number and a PIN.",
                    "Install the AgriPulse Scout app on the phone and sign in.",
                    "Check the phone number before you save. It cannot be changed afterwards.",
                ],
                "note": "A wrong phone number cannot be corrected. The sign-in name is set once, "
                        "at creation. Delete the scout and enrol them again.",
            },
            {
                "t": "Send a visit",
                "where": "Action Center → Dispatch",
                "steps": [
                    "Pick the block and the form to fill.",
                    "Choose the scout. They get the visit in the app and a push notice.",
                    "A decision tree can also open a visit on its own when an index drops.",
                ],
            },
            {
                "t": "Record in the field",
                "where": "AgriPulse Scout, on the phone",
                "steps": [
                    "Open the visit, fill the form, attach photographs.",
                    "The phone records where the observation was taken.",
                    "Submit. The observation lands on the block, on today's date.",
                ],
            },
            {
                "t": "Bring in lab results",
                "where": "Signals → Import",
                "steps": [
                    "Upload a CSV file of results, for example petiole nitrogen from the lab.",
                    "Map the columns to signal codes.",
                    "Imported values read the same as values recorded on a phone.",
                ],
            },
        ],
        "check": [
            "The observation shows on the block, with the date and the scout's name.",
            "A photograph opens from the observation.",
            "A tree that reads that signal picks it up on the next run.",
        ],
        "related": [("kb-signals", "Scouting signal catalog"), ("kb-trees", "Decision tree library")],
    },
    {
        "slug": "process-close-the-loop",
        "num": "07",
        "img": "p07-act",
        "title": "Close the loop",
        "tile": "Work the queue: read why an item opened, give it to someone, and close it with "
                "what actually happened.",
        "lede": "An open recommendation that nobody closes is noise. This process works the queue "
                "from top to bottom and records the outcome, which is what makes next season's "
                "numbers worth reading.",
        "who": "Farm manager, agronomist",
        "time": "20 minutes a day",
        "clip": "10 minutes",
        "start": [
            "At least one published decision tree. See Write the agronomy.",
            "A roster of workers, so items can be handed to someone.",
        ],
        "stages": [
            {
                "t": "Open the queue",
                "where": "Action Center",
                "steps": [
                    "Recommendations and alerts for this farm sit in one list.",
                    "Filter by state and by how soon the action is due.",
                    "Work from the shortest horizon down.",
                ],
            },
            {
                "t": "Read why it opened",
                "where": "Action Center → item → Why this",
                "steps": [
                    "The item names the tree, the values it read, and the threshold it crossed.",
                    "Check the block on the map before you send anyone.",
                    "If the reason is wrong, the threshold needs changing, not the item.",
                ],
            },
            {
                "t": "Give it to someone",
                "where": "Action Center → Assign",
                "steps": [
                    "Assign to the person responsible for the block, or to another member.",
                    "Assignment does not send anyone to the field on its own.",
                ],
            },
            {
                "t": "Dispatch the work",
                "where": "Action Center → Dispatch",
                "steps": [
                    "Send the job to a worker on the roster, or a visit to a scout.",
                    "The person gets it in the app and as a push notice.",
                ],
            },
            {
                "t": "Close it with an outcome",
                "where": "Action Center → Close",
                "steps": [
                    "Say what was done, or why nothing was done.",
                    "The outcome is stored with the item and the tree that opened it.",
                    "This is the record that tells you next season which rules were worth keeping.",
                ],
            },
            {
                "t": "Report the period",
                "where": "Reports",
                "steps": [
                    "Generate a farm report for the period.",
                    "It carries what opened, what was done, and the index history behind it.",
                ],
            },
        ],
        "check": [
            "The queue is shorter at the end of the day than at the start.",
            "Every closed item names an outcome.",
            "The report for the week matches what your team did.",
        ],
        "related": [("kb-trees", "Decision tree library"), ("concepts", "Key concepts")],
    },
    {
        "slug": "process-operate-the-platform",
        "num": "08",
        "img": "p08-platform",
        "title": "Run the platform",
        "tile": "For the operator: tenants, roles, shared catalogs, backfills, health, and "
                "removing an account for good.",
        "lede": "This process is for whoever runs AgriPulse itself, not for a farm. It covers "
                "creating an account, deciding who may do what, maintaining the shared catalogs, "
                "and watching that data keeps arriving.",
        "who": "Platform admin",
        "time": "Ongoing",
        "clip": "14 minutes",
        "start": [
            "A platform admin sign-in.",
            "The customer's name, country and first admin user.",
        ],
        "stages": [
            {
                "t": "Create the tenant",
                "where": "Platform → Tenants",
                "steps": [
                    "Create the account. Each tenant gets its own separate data.",
                    "Provision the first admin user for the customer.",
                    "The new account already reads every seeded catalog.",
                ],
            },
            {
                "t": "Set roles and capabilities",
                "where": "Platform → Roles and permissions",
                "steps": [
                    "A role is a set of single permissions, for example open a recommendation.",
                    "Read the page before changing a role. It lists every permission and who holds it.",
                    "Farm scope is separate: it limits a member to named farms.",
                ],
            },
            {
                "t": "Set the platform defaults",
                "where": "Platform → Defaults",
                "steps": [
                    "Defaults are what a new tenant inherits, for example the grid anomaly threshold.",
                    "Changing a default does not change tenants that already set their own value.",
                ],
            },
            {
                "t": "Maintain the catalogs",
                "where": "Platform → Catalog, Crops, Signals, Plan templates",
                "steps": [
                    "Crops, indices, signal definitions and plan templates are shared by all tenants.",
                    "An improvement to a seeded form reaches every customer.",
                    "A tenant's own row shadows the shared one when the codes collide.",
                ],
            },
            {
                "t": "Run backfills",
                "where": "Platform → Backfill",
                "steps": [
                    "Start a backfill for a farm and a date range.",
                    "Watch the run to the end. A long range takes hours.",
                    "Aggregates can lag the raw data. Give the summary tables time to refresh.",
                ],
            },
            {
                "t": "Watch acquisition health",
                "where": "Platform → Observer, Platform → Integrations health",
                "steps": [
                    "Observer follows passes and computation across every tenant.",
                    "Check it when a customer says the map stopped updating.",
                    "Read it per farm, not per block. Farm-level fetching leaves no block-level job.",
                ],
            },
            {
                "t": "Archive and purge",
                "where": "Platform → Tenants → Purge",
                "steps": [
                    "Archiving comes before purging. A purge cannot be undone.",
                    "Read the receipt. It lists exactly what was removed.",
                ],
                "note": "A purge deletes customer data for good. Confirm the account name against "
                        "the contract before you start.",
            },
        ],
        "check": [
            "The new tenant can sign in and see an empty farm list.",
            "Observer reports passes arriving for the customer's first farm.",
            "The roles page shows the permissions you intended.",
        ],
        "related": [("kb-platform", "Platform catalogs"), ("kb", "Knowledge Base")],
    },
]


# ===========================================================================
# Knowledge Base — by crop
# ===========================================================================

def crop_page(slug, img, title, ar, tile, lede, sections, depth, related=None):
    return {"slug": slug, "img": img, "title": title, "ar": ar, "tile": tile, "lede": lede,
            "sections": sections, "depth": depth, "related": related or []}


CROPS = [
    crop_page(
        "kb-crop-mango", "crop-mango", "Mango", "مانجو",
        "6 decision trees, 6 stages, 6 cultivar plan templates. The deepest crop in the platform.",
        "Mango is the crop AgriPulse knows best. It has a stage model, six cultivar plan "
        "templates, and six decision trees covering disease pressure, canopy health, stress "
        "induction and post-harvest nutrition.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "mango"], ["Arabic name", "مانجو"],
                         ["Scientific name", "Mangifera indica"], ["Category", "fruit_tree"],
                         ["Perennial", "yes"], ["Indices that matter", "ndvi, ndre, ndwi"]]}},
            {"h": "Cultivars with their own plan template", "list": [
                "mango.alphonso", "mango.crimson", "mango.keitt", "mango.sukkary",
                "mango.yasmina", "mango.zebda"]},
            {"h": "Growth stages", "text":
                "Calendar based, by day of year: pre_flowering, flowering, fruit_set, "
                "fruit_development, maturation, post_harvest_flush. A decision tree can read the "
                "stage directly, so a rule can say at flowering rather than in March."},
            {"h": "Decision trees for mango", "table": {
                "cols": ["Tree", "What it reads", "What it opens"],
                "rows": [
                    ["mango_anthracnose_risk_v1", "warm and wet day risk score", "scouting visit and a protective spray decision"],
                    ["mango_powdery_mildew_risk_v1", "weather risk score", "spray decision"],
                    ["mango_fruit_fly_risk_v1", "weather and crop stage", "trapping and monitoring"],
                    ["mango_canopy_health_v1", "vegetation index against baseline", "inspection of the block"],
                    ["mango_stress_induction_v1", "crop stage and water status", "irrigation decision before flowering"],
                    ["mango_post_harvest_nitrogen_v1", "crop stage", "fertiliser timing after harvest"]]}},
            {"h": "Plan template activities", "text":
                "The mango templates carry irrigation, fertilizing, pruning, growth regulator, "
                "harvesting and observation activities, anchored to the stage they belong to."},
        ],
        "Stage model, 6 cultivar templates, 6 decision trees",
        [("kb-trees", "Decision tree library"), ("kb-phenology", "Phenology models")]),

    crop_page(
        "kb-crop-date-palm", "crop-date-palm", "Date palm", "نخيل البلح",
        "7 cultivar plan templates, a 7-stage model from dormancy to tamar, and 3 decision trees.",
        "Date palm has the fullest stage model in the platform, running from dormancy through "
        "the four fruit stages known in the field as kimri, khalal, rutab and tamar. Rain during "
        "pollination and during ripening are both covered by their own rule.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "date_palm"], ["Arabic name", "نخيل البلح"],
                         ["Scientific name", "Phoenix dactylifera"], ["Category", "fruit_tree"],
                         ["Perennial", "yes"], ["Indices that matter", "ndvi, ndwi"]]}},
            {"h": "Cultivars with their own plan template", "list": [
                "date_palm.amhat", "date_palm.barhi", "date_palm.hayany", "date_palm.medjool",
                "date_palm.samany", "date_palm.siwi", "date_palm.zaghloul"]},
            {"h": "Growth stages", "text":
                "Calendar based, by day of year: dormancy, pollination, fruit_set, kimri, khalal, "
                "rutab, tamar. The names are the ones used in the field, not translations."},
            {"h": "Decision trees for date palm", "table": {
                "cols": ["Tree", "What it reads", "Why it matters"],
                "rows": [
                    ["date_palm_pollination_rain_v1", "rainfall during pollination", "rain during pollination costs fruit set"],
                    ["date_palm_ripening_rain_risk_v1", "rainfall during ripening", "rain on ripening fruit causes splitting and rot"],
                    ["date_palm_soil_salinity_v1", "salinity signal from the field or the lab", "salt builds up under palm irrigation"]]}},
            {"h": "Attributes recorded at establishment", "list": [
                "propagation_source: offshoot or tissue culture",
                "offshoot_age_months, offshoot_weight_kg, mother_palm_ref",
                "tc_lab_source and tc_batch_code for tissue culture material"]},
        ],
        "7-stage model, 7 cultivar templates, 3 decision trees",
        [("kb-attributes", "Crop attributes"), ("kb-trees", "Decision tree library")]),

    crop_page(
        "kb-crop-potato", "crop-potato", "Potato", "بطاطس",
        "A days-from-planting stage model, season templates, and 6 rules including the three "
        "petiole tests.",
        "Potato is the annual crop with the most depth. Its stage model counts days from "
        "planting rather than the calendar, and three of its rules read laboratory petiole "
        "results imported from a CSV file.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "potato"], ["Arabic name", "بطاطس"],
                         ["Scientific name", "Solanum tuberosum"], ["Category", "vegetable"],
                         ["Perennial", "no"], ["Indices that matter", "ndvi, ndre, ndwi"]]}},
            {"h": "Varieties in the seed", "list": [
                "potato.spunta", "potato.diamant", "potato.hermes", "potato.cara",
                "potato.lady_rosetta"]},
            {"h": "Growth stages", "text":
                "Counted in days from planting: emergence, tuber_initiation, tuber_bulking, "
                "maturation. Because it counts from your planting date, two blocks planted a "
                "month apart are read correctly at the same time."},
            {"h": "Decision trees for potato", "table": {
                "cols": ["Tree", "What it reads"],
                "rows": [
                    ["potato_frost_risk_v1", "minimum temperature against the frost threshold"],
                    ["potato_heat_stress_v1", "maximum temperature during tuber bulking"],
                    ["potato_petiole_nitrogen_v1", "laboratory petiole nitrogen"],
                    ["potato_petiole_phosphorus_v1", "laboratory petiole phosphorus"],
                    ["potato_petiole_potassium_v1", "laboratory petiole potassium"],
                    ["potato_soil_salinity_v1", "salinity signal"]]}},
            {"h": "Plan template activities", "text":
                "The potato season templates carry soil preparation, planting, irrigation, "
                "fertilizing, hilling, spraying, observation and harvesting."},
            {"h": "Attributes recorded at planting", "list": [
                "seed_material and planting_material",
                "seed_tuber_grade, seed_generation, seed_lot_code",
                "sprouting_status and seed_treatment"]},
        ],
        "Stage model, season templates, 6 decision trees",
        [("kb-signals", "Scouting signal catalog"), ("kb-plans", "Plan templates")]),

    crop_page(
        "kb-crop-citrus", "crop-citrus", "Citrus", "موالح",
        "Orange and mandarin, with a cultivar path already in the taxonomy and no rules written "
        "yet.",
        "Citrus is in the catalog as two crops, orange and mandarin, and the taxonomy already "
        "carries a cultivar path. No citrus decision trees or plan templates ship yet.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Code", "English", "Arabic", "Category", "Perennial"],
                "rows": [["citrus_orange", "Orange", "برتقال", "fruit_tree", "yes"],
                         ["citrus_mandarin", "Mandarin", "يوسفي", "fruit_tree", "yes"]]}},
            {"h": "Taxonomy", "text":
                "citrus.valencia is seeded as a cultivar path, so a rule or a plan can be written "
                "for it as soon as one exists."},
            {"h": "What is not seeded yet", "list": [
                "No phenology model, so growth stage is not available as a condition source.",
                "No plan template.",
                "No citrus decision tree. The general NDVI baseline rule still applies."]},
        ],
        "Catalog and taxonomy only",
        [("kb-taxonomy", "Taxonomy and cultivars"), ("kb-trees", "Decision tree library")]),

    crop_page(
        "kb-crop-olive", "crop-olive", "Olive", "زيتون",
        "In the catalog as a perennial tree crop. Read with the general vegetation rules.",
        "Olive ships in the catalog as a perennial tree crop. It has no stage model and no rule "
        "of its own, so it is watched with the general vegetation and moisture indices and the "
        "baseline alert.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "olive"], ["Arabic name", "زيتون"],
                         ["Scientific name", "Olea europaea"], ["Category", "fruit_tree"],
                         ["Perennial", "yes"], ["Indices that matter", "ndvi"]]}},
            {"h": "How to watch it today", "list": [
                "NDVI against the block baseline, using ndvi_baseline_alert_v1.",
                "NDMI or MSI for canopy moisture during a dry spell.",
                "Thermal, where the farm is subscribed to it, for water stress."]},
            {"h": "What is missing", "text":
                "A stage model and a set of olive rules would be the next thing to add. Olive is "
                "a candidate for the same treatment mango received."},
        ],
        "Catalog only",
        [("kb-indices", "Imagery index catalog")]),

    crop_page(
        "kb-crop-cereals", "crop-cereals", "Cereals and field crops", "حبوب ومحاصيل حقلية",
        "Wheat, maize, rice, and the oilseed, legume and fodder crops. Growing days and heat "
        "sums are seeded for each.",
        "Nine field crops ship in the catalog with growing days and growing degree day limits. "
        "They have no stage models or rules of their own yet, and are read with the general "
        "vegetation and water indices.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Code", "English", "Arabic", "Category", "Growing days", "GDD base to upper"],
                "rows": [
                    ["wheat", "Wheat", "قمح", "cereal", "—", "—"],
                    ["maize", "Maize", "ذرة شامية", "cereal", "110", "10 to 30 °C"],
                    ["rice", "Rice", "أرز", "cereal", "130", "10 to 35 °C"],
                    ["soybean", "Soybean", "فول الصويا", "legume", "—", "—"],
                    ["peanut", "Peanut", "فول سوداني", "legume", "—", "—"],
                    ["sunflower", "Sunflower", "عباد الشمس", "oilseed", "—", "—"],
                    ["sesame", "Sesame", "سمسم", "oilseed", "100", "15 to 35 °C"],
                    ["alfalfa", "Alfalfa", "برسيم حجازي", "fodder", "—", "—"],
                    ["egyptian_clover", "Egyptian clover", "برسيم مصري", "fodder", "—", "—"]]}},
            {"h": "Indices to start with", "list": [
                "Wheat and maize: ndvi and ndre.",
                "Rice: ndvi and ndwi, because standing water changes what the canopy looks like.",
                "Sparse or early stands: savi and msavi, which correct for the soil showing through."]},
            {"h": "What is not seeded yet", "text":
                "No stage models and no crop-specific rules. The growing degree day figures are "
                "there, so a heat-sum rule is the shortest thing to add."},
        ],
        "Catalog only, with growing days and heat sums",
        [("kb-indices", "Imagery index catalog"), ("kb-weather", "Weather catalog")]),

    crop_page(
        "kb-crop-tomato", "crop-vegetables", "Tomato", "طماطم",
        "In the catalog with a taxonomy path and transplant attributes for seedlings.",
        "Tomato ships in the catalog with a taxonomy path and the transplant attributes a "
        "nursery-raised crop needs. No stage model or rule yet.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "tomato"], ["Arabic name", "طماطم"],
                         ["Scientific name", "Solanum lycopersicum"], ["Category", "vegetable"],
                         ["Perennial", "no"], ["Indices that matter", "ndvi, ndre"]]}},
            {"h": "Attributes for transplanted crops", "list": [
                "seedling_age_days", "true_leaves_at_transplant", "tray_cell_count",
                "rootstock_cultivar for grafted plants", "nursery_name"]},
            {"h": "What is not seeded yet", "list": [
                "No stage model.", "No plan template.", "No tomato decision tree."]},
        ],
        "Catalog and transplant attributes",
        [("kb-attributes", "Crop attributes")]),

    crop_page(
        "kb-crop-onion", "crop-onion", "Onion and garlic", "بصل وثوم",
        "Two long-season bulb crops, seeded with their growing days and heat limits.",
        "Onion and garlic are in the catalog as long-season vegetables. Garlic carries the "
        "longest growing-days figure in the whole catalog.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Code", "English", "Arabic", "Growing days", "GDD base to upper", "Indices"],
                "rows": [["onion", "Onion", "بصل", "150", "5 to 25 °C", "ndvi"],
                         ["garlic", "Garlic", "ثوم", "200", "5 to 25 °C", "ndvi"]]}},
            {"h": "How to watch them today", "list": [
                "NDVI against the block baseline through bulking.",
                "The rainfall against evapotranspiration balance, because both crops are "
                "irrigation-sensitive late in the season."]},
            {"h": "What is not seeded yet", "text":
                "No stage model, no plan template and no rule. The long season and the low heat "
                "limits make these good candidates for a growing degree day rule."},
        ],
        "Catalog only",
        [("kb-weather", "Weather catalog")]),

    crop_page(
        "kb-crop-banana", "crop-banana", "Banana", "موز",
        "A perennial in the catalog, watched with vegetation and water indices.",
        "Banana ships in the catalog as a perennial. It has no stage model or rule of its own, "
        "and is watched with the vegetation and water indices.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "banana"], ["Arabic name", "موز"],
                         ["Scientific name", "Musa"], ["Category", "fruit_tree"],
                         ["Perennial", "yes"], ["Indices that matter", "ndvi, ndwi"]]}},
            {"h": "What is not seeded yet", "list": [
                "No stage model.", "No plan template.", "No banana decision tree."]},
        ],
        "Catalog only",
        [("kb-indices", "Imagery index catalog")]),

    crop_page(
        "kb-crop-grape", "crop-grape", "Grape", "عنب",
        "A perennial vine in the catalog, read with the red edge and moisture indices.",
        "Grape ships in the catalog as a perennial. Vines respond early in the red edge, so NDRE "
        "is worth turning on where the farm grows them.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "grape"], ["Arabic name", "عنب"],
                         ["Scientific name", "Vitis vinifera"], ["Category", "fruit_tree"],
                         ["Perennial", "yes"], ["Indices that matter", "ndvi, ndre"]]}},
            {"h": "A note on row crops seen from orbit", "text":
                "A trellised vineyard is mostly bare ground between rows. On a 10 metre pixel the "
                "soil is inside the reading, so SAVI or MSAVI often tracks the canopy better than "
                "NDVI does."},
            {"h": "What is not seeded yet", "list": [
                "No stage model.", "No plan template.", "No grape decision tree."]},
        ],
        "Catalog only",
        [("kb-indices", "Imagery index catalog")]),

    crop_page(
        "kb-crop-cotton", "crop-industrial", "Cotton", "قطن",
        "The one fibre crop in the catalog, and a good fit for the base 15 °C heat sum.",
        "Cotton is the only fibre crop in the catalog. The platform seeds a growing degree day "
        "signal at base 15 °C for warm-season crops like this one.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Field", "Value"],
                "rows": [["Code", "cotton"], ["Arabic name", "قطن"],
                         ["Scientific name", "Gossypium"], ["Category", "fiber"],
                         ["Perennial", "no"], ["Indices that matter", "ndvi, ndre"]]}},
            {"h": "The heat sum that fits it", "text":
                "gdd_base15 is seeded for warm-season crops such as cotton and maize. It is a "
                "daily number, and the season-cumulative version runs from your planting date."},
            {"h": "What is not seeded yet", "list": [
                "No stage model.", "No plan template.", "No cotton decision tree."]},
        ],
        "Catalog only",
        [("kb-weather", "Weather catalog")]),

    crop_page(
        "kb-crop-sugar", "crop-sugar", "Sugar crops", "محاصيل سكرية",
        "Sugarcane and sugar beet. One perennial, one annual, both long season.",
        "Two sugar crops ship in the catalog. Sugarcane is perennial and ratoons for several "
        "years, sugar beet is an annual root crop.",
        [
            {"h": "In the crop catalog", "table": {
                "cols": ["Code", "English", "Arabic", "Category", "Perennial"],
                "rows": [["sugarcane", "Sugarcane", "قصب السكر", "sugar", "yes"],
                         ["sugar_beet", "Sugar beet", "بنجر السكر", "sugar", "no"]]}},
            {"h": "How to watch them today", "list": [
                "NDVI against the baseline across a long season.",
                "NDWI where flood irrigation puts water on the surface.",
                "The rainfall against evapotranspiration balance, because both crops use a lot of water."]},
            {"h": "What is not seeded yet", "list": [
                "No stage model.", "No plan template.", "No rule of their own."]},
        ],
        "Catalog only",
        [("kb-weather", "Weather catalog")]),
]


# ===========================================================================
# Knowledge Base — across all crops
# ===========================================================================

KB = [
    {
        "slug": "kb-indices",
        "img": "kb-indices",
        "title": "Imagery index catalog",
        "tile": "12 indices, optical and thermal, with the bands each one needs and the question "
                "it answers.",
        "lede": "Twelve indices ship in the shared catalog. Each carries a name in two languages, "
                "a unit, the formula, the bands it needs and the satellite product it comes from.",
        "sections": [
            {
                "h": "The catalog",
                "table": {
                    "cols": ["Code", "Name", "Family", "Reads", "Source"],
                    "rows": [
                        ["ndvi", "Normalized Difference Vegetation Index", "vegetation", "red, near infrared", "optical"],
                        ["ndre", "Normalized Difference Red Edge", "vegetation", "red edge, near infrared", "optical"],
                        ["evi", "Enhanced Vegetation Index", "vegetation", "blue, red, near infrared", "optical"],
                        ["savi", "Soil Adjusted Vegetation Index", "vegetation", "red, near infrared", "optical"],
                        ["msavi", "Modified Soil Adjusted Vegetation Index", "vegetation", "red, near infrared", "optical"],
                        ["ndwi", "Normalized Difference Water Index", "surface water", "green, near infrared", "optical"],
                        ["ndmi", "Normalized Difference Moisture Index", "canopy moisture", "near infrared, short wave infrared", "optical"],
                        ["msi", "Moisture Stress Index", "canopy moisture", "near infrared, short wave infrared", "optical"],
                        ["bsi", "Bare Soil Index", "soil", "blue, red, near infrared, short wave infrared", "optical"],
                        ["lst", "Land Surface Temperature", "thermal", "thermal band", "Landsat thermal"],
                        ["cwsi", "Crop Water Stress Index", "thermal", "surface temperature and weather", "Landsat thermal"],
                        ["smi", "Soil Moisture Index", "thermal", "surface temperature and NDVI", "Landsat thermal"],
                    ],
                },
            },
            {
                "h": "Which index answers which question",
                "table": {
                    "cols": ["Question", "Start with"],
                    "rows": [
                        ["How much green canopy is there", "ndvi, evi"],
                        ["Is the canopy dense enough to trust ndvi", "savi, msavi on sparse stands"],
                        ["Is nitrogen or chlorophyll falling in a tree crop", "ndre"],
                        ["Is the canopy losing water", "ndmi, msi"],
                        ["Is there standing water on the surface", "ndwi"],
                        ["How much bare soil is showing", "bsi"],
                        ["Is the crop hot because it is short of water", "lst, cwsi"],
                        ["Is the soil drying out", "smi"],
                    ],
                },
            },
        ],
        "note": ("NDWI here is the surface water index. A high value means water on the ground, "
                 "not a healthy canopy. For canopy moisture use NDMI or MSI. Thermal indices come "
                 "from a different satellite, with a coarser pixel and a longer gap between passes, "
                 "and they are not computed per grid cell."),
        "related": [("kb-weather", "Weather catalog"), ("process-read-the-field", "Read the field")],
    },
    {
        "slug": "kb-weather",
        "img": "kb-weather",
        "title": "Weather catalog",
        "tile": "One provider, six derived daily signals, nine dashboard indices, and the risk "
                "scores the disease rules read.",
        "lede": "Weather is pulled every day for each subscribed farm, history and forecast from "
                "the same provider. The daily job then computes derived signals the rest of the "
                "platform reads.",
        "sections": [
            {
                "h": "Six derived daily signals",
                "table": {
                    "cols": ["Code", "Name", "Unit"],
                    "rows": [
                        ["gdd_base10", "Growing degree days, base 10 °C", "°C·day"],
                        ["gdd_base15", "Growing degree days, base 15 °C", "°C·day"],
                        ["gdd_cumulative_base10_season", "Season cumulative growing degree days, base 10 °C", "°C·day"],
                        ["et0", "Reference evapotranspiration, Penman-Monteith", "mm"],
                        ["rain_7d", "Rainfall, 7 day total", "mm"],
                        ["rain_30d", "Rainfall, 30 day total", "mm"],
                    ],
                },
            },
            {
                "h": "Nine weather indices on the dashboard",
                "table": {
                    "cols": ["Code", "Name"],
                    "rows": [
                        ["temperature", "Maximum and minimum temperature"],
                        ["radiation", "Solar radiation"],
                        ["wind", "Wind speed and direction"],
                        ["rainfall", "Rainfall amount and density"],
                        ["humidity", "Humidity"],
                        ["evapotranspiration", "Plant water loss, ET₀"],
                        ["evaporation_coeff", "Soil dry-down and water deficit"],
                        ["rain_et_balance", "Rainfall against evapotranspiration"],
                        ["drought_spi", "Drought, standardised precipitation index over 90 days"],
                    ],
                },
            },
            {
                "h": "Risk scores",
                "text": "Warm and wet day counts are accumulated into risk scores. The mango "
                        "anthracnose and powdery mildew trees read them, as do the date palm rain "
                        "rules. A risk score is a rule of thumb, not a validated infection model.",
            },
        ],
        "note": "Forecast days are marked as forecast. They are excluded from baselines and from "
                "summary figures, so a hot forecast cannot move a historic average.",
        "related": [("kb-indices", "Imagery index catalog"), ("kb-trees", "Decision tree library")],
    },
    {
        "slug": "kb-trees",
        "img": "kb-trees",
        "title": "Decision tree library",
        "tile": "All 18 agronomy rules, with cited evidence, tunable thresholds and a "
                "transferability rating.",
        "lede": "Eighteen decision trees ship as versioned files. Unlike the other catalogs they "
                "carry scientific provenance: a confidence level, notes, citations, and a rating "
                "for how well the rule transfers to Egypt, the Middle East and the wider world.",
        "sections": [
            {
                "h": "The library",
                "table": {
                    "cols": ["Tree", "Crop", "What it reads"],
                    "rows": [
                        ["mango_anthracnose_risk_v1", "mango", "warm and wet day risk score through flowering and fruit development"],
                        ["mango_powdery_mildew_risk_v1", "mango", "weather risk score"],
                        ["mango_fruit_fly_risk_v1", "mango", "weather and crop stage"],
                        ["mango_canopy_health_v1", "mango", "vegetation index against baseline"],
                        ["mango_stress_induction_v1", "mango", "crop stage and water status"],
                        ["mango_post_harvest_nitrogen_v1", "mango", "crop stage"],
                        ["date_palm_pollination_rain_v1", "date palm", "rainfall during pollination"],
                        ["date_palm_ripening_rain_risk_v1", "date palm", "rainfall during ripening"],
                        ["date_palm_soil_salinity_v1", "date palm", "salinity signal"],
                        ["potato_frost_risk_v1", "potato", "minimum temperature"],
                        ["potato_heat_stress_v1", "potato", "maximum temperature"],
                        ["potato_petiole_nitrogen_v1", "potato", "laboratory petiole result"],
                        ["potato_petiole_phosphorus_v1", "potato", "laboratory petiole result"],
                        ["potato_petiole_potassium_v1", "potato", "laboratory petiole result"],
                        ["potato_soil_salinity_v1", "potato", "salinity signal"],
                        ["ndvi_baseline_alert_v1", "any crop", "NDVI against the block baseline"],
                        ["demo_cell_low_ndvi_v1", "any crop", "NDVI per grid cell"],
                        ["scout_for_stress_v1", "any crop", "an index drop, and opens a scouting visit"],
                    ],
                },
            },
            {
                "h": "What a tree file carries",
                "list": [
                    "Names and descriptions in English and Arabic.",
                    "The crop path it targets, and the regions it applies to.",
                    "An evidence block: confidence, notes, and citations with the source type.",
                    "A transferability rating for Egypt, the Middle East and globally.",
                    "Named parameters with defaults, minimums and maximums, that a tenant can override.",
                ],
            },
            {
                "h": "Example: mango anthracnose",
                "text": "Anthracnose needs warm temperatures around 24 to 30 °C and long leaf "
                        "wetness. The tree accumulates warm wet days and, above the threshold, "
                        "opens a scouting visit and a protective spray decision. Confidence is "
                        "recorded as medium, and the notes state plainly that the score is a rule "
                        "of thumb, not a validated infection model. Default warning score is 40, "
                        "and a tenant can change it.",
            },
        ],
        "note": "Every threshold is a named parameter. Change the parameter for your farm rather "
                "than editing the tree, so you keep the update when the library improves.",
        "related": [("process-author-the-agronomy", "Write the agronomy"), ("kb-crop-mango", "Mango"),
                    ("kb-signals", "Scouting signal catalog")],
    },
    {
        "slug": "kb-signals",
        "img": "kb-signals",
        "title": "Scouting signal catalog",
        "tile": "9 shared field observations and 5 forms, so every farm records the same thing "
                "the same way.",
        "lede": "Nine signal definitions and five forms are seeded for every tenant. They are the "
                "shared vocabulary of the field: without them there is no form for the phone app "
                "to render.",
        "sections": [
            {
                "h": "The nine definitions",
                "table": {
                    "cols": ["Code", "Kind", "Values", "How readings combine"],
                    "rows": [
                        ["canopy_vigour", "categorical", "good, fair, poor, severe", "latest"],
                        ["pest_incidence_pct", "numeric", "percent, 0 to 100", "mean"],
                        ["disease_severity", "categorical", "severity classes", "latest"],
                        ["disease_symptom", "categorical", "anthracnose, powdery, leaf_spot, necrosis, chlorosis, unknown", "latest"],
                        ["weed_pressure", "categorical", "pressure classes", "latest"],
                        ["soil_moisture_feel", "categorical", "by hand in the field", "latest"],
                        ["stress_cause_observed", "categorical", "water, nutrition, pest, disease, salinity, mechanical, none", "latest"],
                        ["irrigation_fault", "event", "recorded when seen", "count"],
                        ["scout_photo", "attachment", "photographs", "count"],
                    ],
                },
            },
            {
                "h": "Rules the engine enforces",
                "list": [
                    "Mean, maximum, minimum and sum work on numbers only.",
                    "Count works on any kind, because it counts rows.",
                    "Anything else falls back to latest. A form that asks for maximum on a "
                    "category is treated as latest.",
                ],
            },
            {
                "h": "Tenant signals",
                "text": "A tenant can author its own signal definitions. A tenant row with the "
                        "same code as a shared one takes priority for that tenant. The shared "
                        "catalog is not changed.",
            },
        ],
        "related": [("process-run-the-field-team", "Run the field team"), ("kb-trees", "Decision tree library")],
    },
    {
        "slug": "kb-phenology",
        "img": "kb-phenology",
        "title": "Phenology models",
        "tile": "Where a crop is in its cycle today, so a rule can say flowering rather than a "
                "date.",
        "lede": "A stage model tells the platform where a crop is in its cycle. Decision trees "
                "read it as the growth stage. Two modes ship: calendar day of year for "
                "perennials, and days from planting for annuals.",
        "sections": [
            {
                "h": "Seeded models",
                "table": {
                    "cols": ["Crop", "Mode", "Stages"],
                    "rows": [
                        ["Mango", "calendar day of year",
                         "pre_flowering, flowering, fruit_set, fruit_development, maturation, post_harvest_flush"],
                        ["Date palm", "calendar day of year",
                         "dormancy, pollination, fruit_set, kimri, khalal, rutab, tamar"],
                        ["Potato", "days from planting",
                         "emergence, tuber_initiation, tuber_bulking, maturation"],
                    ],
                },
            },
            {
                "h": "Why it matters",
                "list": [
                    "The same index value means different things at flowering and at maturation.",
                    "A rain warning during pollination is urgent. The same rain a month later is not.",
                    "Stage is one of the sources a decision tree condition can read.",
                ],
            },
            {
                "h": "Crops with no stage model yet",
                "text": "Twenty of the 23 crops have no stage model. For those, a rule reads the "
                        "index, the weather and the field signals, but cannot say at flowering.",
            },
        ],
        "related": [("kb-crop-mango", "Mango"), ("kb-crop-date-palm", "Date palm"), ("kb-crop-potato", "Potato")],
    },
    {
        "slug": "kb-taxonomy",
        "img": "kb-taxonomy",
        "title": "Taxonomy and cultivars",
        "tile": "Crop paths like mango.sukkary, so a rule can target one cultivar instead of a "
                "whole species.",
        "lede": "A crop has a dotted path. A decision tree, a plan template or a report can aim "
                "at any level of it. This is how one library serves a farm growing six mango "
                "cultivars with different calendars.",
        "sections": [
            {
                "h": "How a path is read",
                "list": [
                    "mango matches every mango block.",
                    "mango.sukkary matches only that cultivar.",
                    "mango.alphonso.short matches a named strain inside a cultivar.",
                    "An empty crop path means the rule runs on any crop.",
                ],
            },
            {
                "h": "Paths in the seed",
                "table": {
                    "cols": ["Path", "Level", "Has a plan template"],
                    "rows": [
                        ["mango.alphonso", "cultivar", "yes"],
                        ["mango.crimson", "cultivar", "yes"],
                        ["mango.keitt", "cultivar", "yes"],
                        ["mango.sukkary", "cultivar", "yes"],
                        ["mango.yasmina", "cultivar", "yes"],
                        ["mango.zebda", "cultivar", "yes"],
                        ["date_palm.zaghloul, samany, hayany, amhat, siwi, barhi, medjool", "cultivar", "yes, all seven"],
                        ["potato.spunta, diamant, hermes, cara, lady_rosetta", "variety", "season templates"],
                        ["citrus.valencia", "cultivar", "no"],
                    ],
                },
            },
            {
                "h": "Canopy size classes",
                "text": "Tree crops also carry a size class: small, medium or large. It changes "
                        "what a rule expects to see from a block of young trees against a block "
                        "of mature ones.",
            },
        ],
        "related": [("kb-crop-mango", "Mango"), ("kb-crop-date-palm", "Date palm")],
    },
    {
        "slug": "kb-attributes",
        "img": "kb-attributes",
        "title": "Crop attributes",
        "tile": "The seeded fields that record how a block was established: rootstock, seed "
                "grade, offshoot age.",
        "lede": "Per-crop fields that a block records once. They ship seeded, so two farms "
                "describe the same thing the same way, and a decision tree can read them as a "
                "condition.",
        "sections": [
            {
                "h": "Examples from the seed",
                "table": {
                    "cols": ["Field", "Used for"],
                    "rows": [
                        ["establishment_method", "how the block was planted"],
                        ["transplant_date, age_at_transplant_months", "tree crops"],
                        ["rootstock_type, graft_union_height_cm", "grafted trees"],
                        ["nursery_source, nursery_name", "where the material came from"],
                        ["offshoot_age_months, offshoot_weight_kg, mother_palm_ref", "date palm"],
                        ["tc_lab_source, tc_batch_code", "tissue culture material"],
                        ["seed_tuber_grade, seed_generation, seed_lot_code, sprouting_status, seed_treatment", "potato"],
                        ["seedling_age_days, true_leaves_at_transplant, tray_cell_count", "transplanted vegetables"],
                    ],
                },
            },
        ],
        "note": "Fill these once, at establishment. They are the only record of why two blocks of "
                "the same cultivar behave differently.",
        "related": [("kb-crop-date-palm", "Date palm"), ("kb-crop-potato", "Potato")],
    },
    {
        "slug": "kb-plans",
        "img": "kb-plans",
        "title": "Plan templates",
        "tile": "Ready season calendars for mango, potato and date palm that a farm copies and "
                "edits.",
        "lede": "A plan template is a season calendar for a crop or a cultivar. A farm starts "
                "from one instead of an empty board, then edits it to match how it actually works.",
        "sections": [
            {
                "h": "What ships",
                "table": {
                    "cols": ["Crop", "Templates", "Activities they carry"],
                    "rows": [
                        ["Mango", "6 cultivar templates: alphonso, crimson, keitt, sukkary, yasmina, zebda",
                         "irrigation, fertilizing, pruning, growth regulator, harvesting, observation"],
                        ["Date palm", "7 cultivar templates: amhat, barhi, hayany, medjool, samany, siwi, zaghloul",
                         "anchored to the stage each job belongs to"],
                        ["Potato", "season templates",
                         "soil preparation, planting, irrigation, fertilizing, hilling, spraying, observation, harvesting"],
                    ],
                },
            },
            {
                "h": "How a template becomes a plan",
                "list": [
                    "You pick the template and a season start date.",
                    "Activity dates shift to match your start date.",
                    "From then on the plan is yours. Later changes to the template do not rewrite it.",
                ],
            },
        ],
        "related": [("kb-crop-mango", "Mango"), ("process-plan-the-season", "Plan the season")],
    },
    {
        "slug": "kb-platform",
        "img": "kb-platform",
        "title": "Platform catalogs",
        "tile": "Countries, defaults, providers, notification templates and the full permission "
                "list.",
        "lede": "The rest of what ships seeded. These are operator-facing catalogs: they decide "
                "what a new tenant inherits and how messages leave the platform.",
        "sections": [
            {
                "h": "What is in here",
                "table": {
                    "cols": ["Catalog", "What it decides"],
                    "rows": [
                        ["Countries", "farm location and the region targeting a decision tree uses"],
                        ["Platform defaults", "the settings a new tenant starts with"],
                        ["Grid anomaly threshold", "how far a cell must move before it is called an anomaly"],
                        ["Imagery providers and products", "where passes come from and which bands arrive"],
                        ["Notification templates", "the wording for alerts and recommendations, in app, by email and by webhook, in English and Arabic"],
                        ["Push templates", "the wording sent to the scouting app"],
                        ["Capability catalog", "every single permission a role can grant"],
                    ],
                },
            },
            {
                "h": "Notification variables",
                "text": "A template can use the tenant, the farm and block, the tree that opened "
                        "the item, the action type, the severity, the text, the time it fired and "
                        "a link back into the app. The webhook channel sends the same fields as JSON.",
            },
        ],
        "related": [("process-operate-the-platform", "Run the platform"), ("concepts", "Key concepts")],
    },
]


# ===========================================================================
# Concepts
# ===========================================================================

CONCEPTS = [
    ("Farm shape", [
        ("Tenant", "One customer account. Its own data, its own users, separate from every other tenant."),
        ("Farm", "A named boundary. Imagery and weather subscriptions attach here, not to blocks."),
        ("Block", "A managed area inside a farm. It carries the crop, the plan and the responsible person."),
        ("Grid cell", "A fixed size square inside a block, used to see variation within the block. "
                      "Cell size is set once per farm."),
        ("Land unit", "An area that is not crop: a road, a building, a canal. Excluded from crop numbers."),
        ("Farm surface", "Whole farm imagery. At the boundary a pixel counts only if its centre "
                         "falls inside the farm."),
    ]),
    ("Data", [
        ("Pass", "One satellite acquisition over the farm on one date. A chart point is a pass, not a day."),
        ("Index", "A number computed from satellite bands, for example NDVI. Twelve ship seeded."),
        ("Aggregate", "The mean, minimum, maximum and percentiles of an index over a block or a cell, per pass."),
        ("Baseline", "What this block usually reads at this time of year. An anomaly is measured against it."),
        ("Weather derived signal", "A daily number computed from the weather feed, for example ET₀ or growing degree days."),
        ("Forecast", "Weather days after today. Marked as forecast and excluded from baselines and summaries."),
        ("Signal", "A value recorded in the field or imported from a laboratory, on a block, on a date."),
    ]),
    ("Logic", [
        ("Decision tree", "A versioned flow of nodes that reads data and opens recommendations or alerts."),
        ("Condition source", "What a condition may read: an index, a weather value, a field signal, "
                             "the crop stage, or a block attribute."),
        ("Parameter", "A named threshold with a default, declared by the tree author and changeable per tenant."),
        ("Scope", "Whether the tree runs once per block or once per grid cell."),
        ("Dry run", "Running a draft against real data without opening anything."),
        ("Evaluation trace", "The stored record of why a tree fired or did not fire on a block."),
    ]),
    ("Action", [
        ("Recommendation", "A dated suggested action on a block or a cell, with the reason it opened."),
        ("Alert", "A dated warning that needs attention. Same origin as a recommendation."),
        ("Action horizon", "How soon the action is due. Four horizons, from immediate to seasonal."),
        ("Dispatch", "Sending an item to a worker or a scout, in the app and as a push notice."),
        ("Visit", "A scouting job on a block, with a form to fill and photographs to attach."),
        ("Plan and activity", "The season calendar for a block, and the jobs on it."),
    ]),
    ("Crop", [
        ("Crop path", "A dotted name such as mango.sukkary. A rule can target any level of it."),
        ("Variety", "The cultivar planted on a block. It can carry its own plan template."),
        ("Growth stage", "Where the crop is in its cycle today, from the phenology model."),
        ("Crop attribute", "A field recorded once at establishment, for example rootstock or seed grade."),
        ("Size class", "Small, medium or large canopy, used for tree crops."),
        ("Growing degree day", "A daily heat sum above a base temperature, used to track development."),
    ]),
    ("People and access", [
        ("Membership and role", "A user's place in a tenant, and what they are allowed to do."),
        ("Capability", "One single permission, for example open a recommendation. A role is a set of them."),
        ("Farm scope", "Limiting a member to named farms."),
        ("Resource", "A person or a machine on the farm roster that work can be given to."),
        ("Platform admin", "Operates AgriPulse across tenants: catalogs, defaults, backfills, Observer."),
    ]),
]


# ===========================================================================
# Photo credits
# ===========================================================================

CREDITS = [
    ("hero-pivots.jpg", "Desert agriculture in Egypt, Copernicus Sentinel-2, 3 February 2024", "European Union, Copernicus Sentinel-2 imagery", "Attribution"),
    ("p01-map.jpg", "Concentric circle farmland", "Flickr, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("p02-season.jpg", "Mango grove, Nueva Ecija", "Wikimedia Commons", "Public domain"),
    ("p03-connect.jpg", "Satellite picture of the Nile Delta, Egypt", "NASA, via Wikimedia Commons", "Public domain"),
    ("p04-read.jpg", "Irrigation in the Egyptian desert", "Wikimedia Commons", "CC BY-SA 2.0"),
    ("p05-agronomy.jpg", "Olive grove, Agii Douli, Corfu", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("p06-team.jpg", "Local mango harvest", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("p07-act.jpg", "Irrigation equipment in an orchard, USDA NRCS", "USDA, via Wikimedia Commons", "CC BY 2.0"),
    ("p08-platform.jpg", "Date palm plantation, Vista Santa Rosa, California", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("kb-hero.jpg", "Citrus crops, Temecula Valley", "Wikimedia Commons", "CC BY 4.0"),
    ("kb-indices.jpg", "Nile delta, Landsat false colour", "NASA, via Wikimedia Commons", "Public domain"),
    ("kb-weather.jpg", "Weather station", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("kb-trees.jpg", "Mango orchard in Lucknow", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("kb-signals.jpg", "Potato harvest, machinery in the field", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("kb-phenology.jpg", "Field beside the weather station", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("kb-taxonomy.jpg", "Date palm plantation north of the Dead Sea", "Mussi Katz, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("kb-attributes.jpg", "Date palm plantation in southern Qatar", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("kb-plans.jpg", "Potato harvest", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("kb-platform.jpg", "Travelling irrigation sprinkler", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-mango.jpg", "Mango orchard in Lucknow", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-date-palm.jpg", "Date palm plantation north of the Dead Sea", "Mussi Katz, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("crop-potato.jpg", "Potato harvest", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("crop-citrus.jpg", "Orange grove, Beldibi", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-olive.jpg", "Olive grove, Agii Douli, Corfu", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-cereals.jpg", "Maize field in Canterbury", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("crop-vegetables.jpg", "Tomato farmer in his field", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-onion.jpg", "Onion field", "Wikimedia Commons", "CC BY-SA 3.0"),
    ("crop-banana.jpg", "Banana garden", "Denis Kasozi, via Wikimedia Commons", "CC BY 4.0"),
    ("crop-grape.jpg", "Rows of vines at Three Choirs Vineyard", "Geograph, via Wikimedia Commons", "CC BY-SA 2.0"),
    ("crop-industrial.jpg", "Cotton field, Floyd County, Georgia", "Wikimedia Commons", "CC BY-SA 4.0"),
    ("crop-sugar.jpg", "Sugarcane field, Cane Farm Road, Alberton", "Wikimedia Commons", "CC BY 4.0"),
]


# ===========================================================================
# Detailed guides — one task, every field, with screenshots
# ===========================================================================

GUIDES = [
    {
        "slug": "guide-create-a-farm",
        "process": ("process-map-the-farm", "Map the farm", "01"),
        "img": "p01-map",
        "title": "Create a farm",
        "short": "Draw the boundary, name the farm, save it. Two screens, two required fields.",
        "lede": "A farm is the outer boundary of everything you manage in one place. Imagery and "
                "weather subscriptions attach to the farm, not to the blocks inside it, so this is "
                "the first record you create and the one everything else hangs off.",
        "who": "Tenant admin, farm manager",
        "time": "5 minutes, once you know where the boundary runs",
        "clip": "4 minutes",
        "clip_file": "farm-creation",
        "clip_poster": "guide-farm-clip-poster",
        "clip_note": ("Silent screen capture of the real app, 1 minute 38 seconds. It covers "
                      "steps 1 to 5 and stops before Create farm. The narrated version replaces "
                      "it once it is recorded."),
        "start": [
            "A tenant account and a sign-in that can create farms.",
            "The boundary: either you know where it runs on the map, or you have a KML, "
            "GeoJSON or zipped Shapefile of it.",
            "A code and a name your team already uses for this farm.",
        ],
        "steps": [
            {
                "t": "Open the new farm flow",
                "img": "guide-farm-01-empty",
                "cap": "The workspace before any farm exists.",
                "body": [
                    "On a new account the workspace opens on <b>No farms yet</b>. Click "
                    "<b>Create your first farm</b>.",
                    "If the account already has farms, go to <b>Farm management</b> and start a new "
                    "farm from there. Both routes open the same two-screen flow at "
                    "<code>/labs/map?create=farm</code>.",
                    "Until a farm exists, Insights, Plan, Signals, Action Center, Recommendations, "
                    "Alerts and Reports are greyed out. They all need a farm to point at.",
                ],
            },
            {
                "t": "Step 1 of 2 — draw or upload the boundary",
                "img": "guide-farm-02-step1",
                "cap": "Step 1. The map opens on satellite imagery so you can trace field edges.",
                "body": [
                    "<b>Draw boundary</b> lets you click each corner of the farm on the map. Click "
                    "once per corner, then double-click the last corner to close the shape.",
                    "<b>Upload file</b> takes a KML, a GeoJSON, or a Shapefile in a zip. Use this "
                    "when a surveyor already gave you the boundary.",
                    "Draw the <b>outer</b> boundary only. Blocks come later, inside it.",
                    "Include the roads, buildings and canals that sit inside the farm. You mark "
                    "them as land units afterwards so they stop counting towards crop numbers.",
                ],
                "note": "Zoom in before you start drawing. A boundary traced at low zoom is off by "
                        "tens of metres, and every index number for this farm is computed inside "
                        "that line.",
            },
            {
                "t": "Check the area before you go on",
                "img": "guide-farm-03-step2",
                "cap": "Step 2. The panel header shows the area of the shape you drew.",
                "body": [
                    "As soon as the shape closes, the panel header shows the area, for example "
                    "<b>185.5 feddan</b>. The unit follows the tenant unit setting: feddan, acre "
                    "or hectare.",
                    "Compare that figure with what you know the farm to be. A number that is far "
                    "out means the shape is wrong, and it is much cheaper to fix now.",
                    "<b>Boundary</b> takes you back to redraw. <b>Cancel</b>, at the top right, "
                    "throws the whole thing away.",
                ],
            },
            {
                "t": "Fill the two required fields",
                "body": [
                    "<b>Code</b> is the short identifier your team uses, for example "
                    "<code>GV-01</code>. It appears in lists, exports and reports.",
                    "<b>Name</b> is the readable name, for example <code>Green Valley North</code>.",
                    "<b>Create farm</b> stays disabled until both Code and Name are filled. Nothing "
                    "else on the form is required.",
                    "Set <b>Country</b> even though it is optional. Decision trees can be written "
                    "for a region, and a farm with no country matches none of them.",
                ],
            },
            {
                "t": "Open More details if you have the answers",
                "img": "guide-farm-04-details",
                "cap": "More details. Every field here is optional and editable later.",
                "body": [
                    "Everything under <b>More details</b> is optional. Skip it if you are recording "
                    "the farm quickly, and come back later.",
                    "<b>Primary water source</b> and <b>Farm type</b> are worth setting now. They "
                    "describe the farm in reports and give context to anyone reading it later.",
                    "<b>Tags</b> are free text. Use them if you group farms by region or by client.",
                ],
            },
            {
                "t": "Create the farm",
                "body": [
                    "Click <b>Create farm</b>.",
                    "The farm appears in the farm picker at the top of the workspace, and the "
                    "workspace pages stop being greyed out.",
                    "Everything except the boundary can be changed later in Farm settings.",
                ],
            },
        ],
        "fields": {
            "cols": ["Field", "Required", "What it is for"],
            "rows": [
                ["Boundary", "yes", "The outer edge of the farm. Drawn on the map, or uploaded as KML, GeoJSON or zipped Shapefile."],
                ["Code", "yes", "Short identifier, for example GV-01. Shows in lists, exports and reports."],
                ["Name", "yes", "Readable name, for example Green Valley North. Shows in the farm picker."],
                ["Country", "no", "One of 18 countries. Decision trees can target a region, so a farm with no country matches none of them."],
                ["Description", "no", "Free text about the farm."],
                ["Governorate, District", "no", "Administrative location."],
                ["Nearest city, Address", "no", "Where the farm is, in words."],
                ["Farm type", "no", "Commercial, Research or Contract. Starts on Commercial."],
                ["Ownership", "no", "Owned, Leased, Partnership or Other."],
                ["Primary water source", "no", "Well, Canal, Nile, Desalinated, Rainfed or Mixed."],
                ["Established date", "no", "When the farm started."],
                ["Tags", "no", "Free text labels for grouping farms."],
            ],
        },
        "mistakes": {
            "cols": ["What you see", "What to do"],
            "rows": [
                ["Create farm is greyed out", "Code or Name is empty. Both are required. Everything else is optional."],
                ["The area looks wrong", "The shape is wrong, not the calculation. Click Boundary and redraw at a higher zoom."],
                ["The boundary cuts through a field", "Redraw before you create blocks. Blocks and grid cells are all computed inside this line."],
                ["No country set", "The farm still works, but a decision tree written for a region will skip it. Set it in Farm settings."],
                ["The upload is rejected", "The file must be KML, GeoJSON, or a Shapefile inside a zip. A bare .shp will not do, a Shapefile needs its sidecar files."],
            ],
        },
        "check": [
            "The farm shows in the farm picker at the top of the workspace.",
            "The area in Farm settings matches what you know the farm to be.",
            "The workspace pages are no longer greyed out.",
        ],
        "next": [("process-map-the-farm", "Back to Map the farm"),
                 ("process-plan-the-season", "Plan the season"),
                 ("concepts", "Key concepts")],
    },
]

# ===========================================================================
# Templates
# ===========================================================================

def e(s) -> str:
    return html.escape(str(s), quote=False)


def head(title: str, desc: str, nav_on: str = "") -> str:
    def navlink(href, label, key):
        on = ' class="on"' if key == nav_on else ""
        return f'<a href="{href}"{on}>{label}</a>'

    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{e(title)} · AgriPulse docs</title>
<meta name="description" content="{e(desc)}" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<link rel="stylesheet" href="assets/site.css" />
</head>
<body>
<header class="site">
  <div class="site-inner">
    <a class="brand" href="index.html">
      <span class="mark">A</span>
      <span>AgriPulse<small>documentation</small></span>
    </a>
    <nav class="main">
      {navlink("index.html#processes", "Processes", "processes")}
      {navlink("kb.html", "Knowledge Base", "kb")}
      {navlink("concepts.html", "Concepts", "concepts")}
      {navlink("support.html", "Support", "support")}
    </nav>
    <span class="site-spacer"></span>
    <button class="hbtn" id="lang" type="button" title="Arabic pages are planned">العربية</button>
    <button class="hbtn" id="theme" type="button">Theme</button>
  </div>
</header>
"""


FOOT = """
<footer class="site">
  <div class="inner">
    <div>
      <a class="brand" href="index.html"><span class="mark">A</span><span>AgriPulse<small>documentation</small></span></a>
      <p>Farm intelligence for Egypt and the region. Satellite, weather and field
         observation in one record, with a dated action at the end of it.</p>
    </div>
    <div>
      <h5>Processes</h5>
      <a href="process-map-the-farm.html">Map the farm</a>
      <a href="process-plan-the-season.html">Plan the season</a>
      <a href="process-connect-the-data.html">Connect the data</a>
      <a href="process-read-the-field.html">Read the field</a>
      <a href="process-author-the-agronomy.html">Write the agronomy</a>
      <a href="process-run-the-field-team.html">Run the field team</a>
      <a href="process-close-the-loop.html">Close the loop</a>
      <a href="process-operate-the-platform.html">Run the platform</a>
    </div>
    <div>
      <h5>Knowledge Base</h5>
      <a href="kb.html">All catalogs</a>
      <a href="kb-crop-mango.html">Mango</a>
      <a href="kb-crop-date-palm.html">Date palm</a>
      <a href="kb-crop-potato.html">Potato</a>
      <a href="kb-indices.html">Imagery indices</a>
      <a href="kb-weather.html">Weather</a>
      <a href="kb-trees.html">Decision trees</a>
      <a href="concepts.html">Key concepts</a>
    </div>
    <div>
      <h5>Support</h5>
      <a href="support.html#faq">FAQs</a>
      <a href="support.html#ask">Ask the AgriPulse team</a>
      <a href="support.html#feature">Request a feature</a>
      <a href="credits.html">Photo credits</a>
      <a href="https://app.agripulse.cloud">Sign in to the app</a>
    </div>
  </div>
  <div class="legal">
    <div class="inner">
      <span>AgriPulse documentation · docs.agripulse.cloud · draft, 18 August 2026</span>
      <span>Photographs are used under the licences listed on the credits page.</span>
    </div>
  </div>
</footer>
<script>
  (function () {
    var order = ["light", "dark", ""];
    document.getElementById("theme").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme") || "";
      var next = order[(order.indexOf(cur) + 1) % order.length];
      if (next) { document.documentElement.setAttribute("data-theme", next); }
      else { document.documentElement.removeAttribute("data-theme"); }
    });
    var lang = document.getElementById("lang");
    lang.addEventListener("click", function () {
      var rtl = document.documentElement.dir === "rtl";
      document.documentElement.dir = rtl ? "ltr" : "rtl";
      lang.textContent = rtl ? "العربية" : "English";
    });
  })();
</script>
</body>
</html>
"""


def tile(href, img, eyebrow, title, text, meta="") -> str:
    meta_html = f'<div class="meta">{e(meta)}</div>' if meta else ""
    return f"""      <a class="tile" href="{href}">
        <div class="shot"><img src="img/{img}.jpg" alt="" loading="lazy" /><span class="num">{e(eyebrow)}</span></div>
        <div class="body">
          <h3>{e(title)}</h3>
          <p>{e(text)}</p>
          {meta_html}
        </div>
      </a>
"""


def table(cols, rows) -> str:
    head_html = "".join(f"<th>{e(c)}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            v = e(c)
            if i == 0 and " " not in str(c) and str(c) == str(c).lower() and any(ch.isalpha() for ch in str(c)):
                v = f"<code>{v}</code>"
            cells.append(f"<td>{v}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="table-wrap"><table><thead><tr>{head_html}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def clip_block(title: str, length: str, file: str = "", poster: str = "", note: str = "") -> str:
    """The video slot. Plays a file when there is one, otherwise shows the placeholder."""
    if file:
        poster_attr = f' poster="img/{poster}.jpg"' if poster else ""
        return f"""    <div class="clip">
      <video controls preload="metadata"{poster_attr} playsinline>
        <source src="media/{file}.mp4" type="video/mp4" />
        Your browser cannot play this video. Download it at
        <a href="media/{file}.mp4">media/{file}.mp4</a>.
      </video>
      <div class="bar">
        <span><b>{e(title)}.</b> {e(note)}</span>
        <span class="chip live">Draft capture</span>
      </div>
    </div>
"""
    return f"""    <div class="clip">
      <div class="frame">
        <div>
          <div class="play"></div>
          <b>{e(title)}</b>
          <span>Screen recording, planned length about {e(length)}. Not recorded yet.</span>
        </div>
      </div>
      <div class="bar">
        <span><b>Video slot.</b> The recording drops in here, with captions in English and Arabic.</span>
        <span class="chip">Not recorded</span>
      </div>
    </div>
"""


def clip_list(stages) -> str:
    rows = "".join(
        f'<div class="row"><span class="ix">{i + 1:02d}</span>'
        f'<span class="t">{e(s["t"])}</span><span class="chip">Not recorded</span></div>'
        for i, s in enumerate(stages))
    return f'<div class="cliplist">{rows}</div>'


def related_block(items) -> str:
    if not items:
        return ""
    links = "".join(
        f'<a class="card" href="{slug}.html"><h4>{e(label)}</h4><p>Open the page</p></a>'
        for slug, label in items)
    return f"""
  <section class="band tint">
    <div class="wrap">
      <p class="kicker">Related</p>
      <h2 class="section">Read next</h2>
      <div class="cards c3" style="margin-top:1.2rem">{links}</div>
    </div>
  </section>
"""


def support_block(heading="Need something else?") -> str:
    cards = "".join(
        f'<a href="support.html#{key}"><div class="ico">{ico}</div><h4>{e(title)}</h4>'
        f'<p>{e(text)}</p><p style="margin-top:.6rem"><span class="chip">{e(state)}</span></p></a>'
        for key, ico, title, text, state in SUPPORT)
    return f"""
  <section class="band">
    <div class="wrap">
      <p class="kicker">Support</p>
      <h2 class="section">{e(heading)}</h2>
      <p class="big" style="max-width:60ch">Three channels beside the documentation. All three
         pages are placeholders for now and will be designed next.</p>
      <div class="support">{cards}</div>
    </div>
  </section>
"""


def pagenav(prev, nxt) -> str:
    left = (f'<a href="{prev[0]}.html"><div class="dir">Previous</div>'
            f'<div class="t">{e(prev[1])}</div></a>') if prev else "<span></span>"
    right = (f'<a class="next" href="{nxt[0]}.html"><div class="dir">Next</div>'
             f'<div class="t">{e(nxt[1])}</div></a>') if nxt else ""
    return f'<div class="wrap"><div class="pagenav">{left}{right}</div></div>'


# ===========================================================================
# Pages
# ===========================================================================

def build_index() -> str:
    ptiles = "".join(
        tile(f'{p["slug"]}.html', p["img"], f'Process {p["num"]}', p["title"], p["tile"],
             f'{len(p["stages"])} steps · guide and clip')
        for p in PROCESSES)
    croptiles = "".join(
        tile(f'{c["slug"]}.html', c["img"], c["ar"], c["title"], c["tile"], c["depth"])
        for c in CROPS)
    pillars = "".join(
        f'<div class="pillar"><div class="n">0{i+1}</div><h4>{e(t)}</h4><p>{e(d)}</p></div>'
        for i, (t, d) in enumerate(PILLARS))
    loop = "".join(f"<li><span><b>{e(t)}.</b> {e(d)}</span></li>" for t, d in LOOP)
    stats = "".join(f'<div class="stat"><div class="v">{e(v)}</div><div class="l">{e(l)}</div></div>'
                    for v, l in STATS)

    return head("Farm intelligence, documented",
                "AgriPulse documentation: eight processes, a knowledge base by crop, and "
                "everything that ships seeded.") + f"""
<section class="hero tight">
  <img class="bg" src="img/hero-pivots.jpg" alt="Satellite view of circular irrigated fields in the Egyptian desert" />
  <div class="inner">
    <span class="eyebrow">AgriPulse documentation</span>
    <h1>From satellite pass to field decision.</h1>
    <p class="lede">How to run the platform, and everything that ships inside it.</p>
    <ul class="pill-row">
      <li><b>Observe</b> satellite, weather, scouts</li>
      <li><b>Interpret</b> indices and baselines</li>
      <li><b>Act</b> dated work your team closes</li>
    </ul>
  </div>
</section>

<section class="band" id="processes" style="padding-top:1.5rem">
  <div class="wrap">
    <p class="kicker">How to</p>
    <h2 class="section">Eight processes, start to finish.</h2>
    <div class="tiles c3">
{ptiles}    </div>
  </div>
</section>

<section class="band tint" id="what">
  <div class="wrap">
    <div class="split">
      <div>
        <p class="kicker">What AgriPulse is</p>
        <h2 class="section">A record of the field, and an action at the end of it.</h2>
        <p class="big">You map your farms and blocks, connect them to satellite and weather data,
           and the platform computes indices for every block and every grid cell on each pass.</p>
        <p>Decision trees read those numbers together with the weather, what your scouts recorded,
           the crop stage and how the block was planted. When a rule matches, a recommendation or
           an alert opens on that block, on that date, with the reason attached. Your team assigns
           it, sends it to a worker or a scout, and closes it with an outcome.</p>
        <p>The platform runs in English and Arabic, and ships with the agronomy already written.</p>
        <div class="pillars">{pillars}</div>
      </div>
      <div class="loop">
        <h4>The loop, in five steps</h4>
        <ol>{loop}</ol>
        <p class="sub" style="margin-top:.9rem">Each step is a process on this site. Start at the
           top if the farm is new, or jump to the step you are stuck on.</p>
      </div>
    </div>
  </div>
</section>

<section class="band" style="padding:2.4rem 0">
  <div class="wrap"><div class="stats">{stats}</div></div>
</section>

<section class="band tint" id="kb">
  <div class="wrap">
    <p class="kicker">Knowledge Base</p>
    <h2 class="section">What ships, crop by crop.</h2>
    <p class="big" style="max-width:64ch">A page per crop: what is in the catalog, which cultivars
       carry a plan template, the growth stages, the rules written for it, and what is still missing.</p>
    <div class="tiles c4">
{croptiles}    </div>
    <p style="margin-top:1.6rem"><a class="btn primary" href="kb.html">Open the Knowledge Base</a>
       <span class="sub" style="margin-left:.6rem">Indices, weather, decision trees, signals and
       the platform catalogs sit there too.</span></p>
  </div>
</section>
{support_block()}
<section class="band tint">
  <div class="wrap narrow" style="text-align:center">
    <p class="kicker">Also here</p>
    <h2 class="section">Key concepts</h2>
    <p>The words the rest of this site uses: farm and block, pass and index, baseline and anomaly,
       tree and trace, recommendation and horizon.</p>
    <p style="margin-top:1.1rem"><a class="btn primary" href="concepts.html">Open the concept list</a></p>
  </div>
</section>
""" + FOOT


def build_process(p, prev, nxt) -> str:
    start = "".join(f"<li>{e(s)}</li>" for s in p["start"])
    stages = []
    for st in p["stages"]:
        steps = "".join(f"<li>{e(s)}</li>" for s in st["steps"])
        where = (f'<div><span class="where"><b>In the app</b> {e(st["where"])}</span></div>'
                 if st.get("where") else "")
        note = (f'<div class="note"><span class="lab">Note</span><p>{e(st["note"])}</p></div>'
                if st.get("note") else "")
        guide = ""
        if st.get("guide"):
            gslug, glabel = st["guide"]
            guide = f'<div><a class="guide-link" href="{gslug}.html">{e(glabel)}</a></div>'
        stages.append(f"""      <div class="stage">
        <div class="badge"></div>
        <div>
          <h3>{e(st["t"])}</h3>
          <ul class="steps">{steps}</ul>
          {where}
          {guide}
          {note}
        </div>
      </div>
""")
    check = "".join(f"<li>{e(c)}</li>" for c in p["check"])

    return head(p["title"], p["lede"][:180], "processes") + f"""
<section class="hero compact">
  <img class="bg" src="img/{p["img"]}.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a> → <a href="index.html#processes">Processes</a></div>
    <span class="eyebrow">Process {e(p["num"])}</span>
    <h1>{e(p["title"])}</h1>
    <p class="lede">{e(p["lede"])}</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="cards c3">
      <div class="card"><h4>Who does this</h4><p>{e(p["who"])}</p></div>
      <div class="card"><h4>How long it takes</h4><p>{e(p["time"])}</p></div>
      <div class="card"><h4>Steps</h4><p>{len(p["stages"])} steps, in order</p></div>
    </div>

    <h3>Watch it in the system</h3>
    <p>A screen recording of the whole process, start to finish, in the real product.</p>
{clip_block(p["title"] + " — full walkthrough", p["clip"])}
  </div>
</section>

<section class="band tint">
  <div class="wrap">
    <p class="kicker">Step by step</p>
    <h2 class="section">The written guide</h2>

    <h3>Before you start</h3>
    <ul>{start}</ul>

    <div class="stages" style="margin-top:2rem">
{"".join(stages)}    </div>

    <div class="note"><span class="lab">Check it worked</span>
      <ul style="margin:.3rem 0 0">{check}</ul>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <p class="kicker">Clips</p>
    <h2 class="section">One short clip per step</h2>
    <p>Beside the full walkthrough, each step gets its own short recording, so you can jump
       straight to the part you need.</p>
{clip_list(p["stages"])}
  </div>
</section>
{related_block(p.get("related"))}
{support_block("Still stuck?")}
<section class="band tint" style="padding-top:0">
{pagenav(prev, nxt)}
</section>
""" + FOOT


def build_kb_index() -> str:
    croptiles = "".join(
        tile(f'{c["slug"]}.html', c["img"], c["ar"], c["title"], c["tile"], c["depth"])
        for c in CROPS)
    ktiles = "".join(
        tile(f'{k["slug"]}.html', k["img"], "Catalog", k["title"], k["tile"]) for k in KB)
    stats = "".join(f'<div class="stat"><div class="v">{v}</div><div class="l">{l}</div></div>'
                    for v, l in STATS)

    return head("Knowledge Base", "Everything that ships seeded with AgriPulse, crop by crop.",
                "kb") + f"""
<section class="hero compact">
  <img class="bg" src="img/kb-hero.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a></div>
    <span class="eyebrow">Knowledge Base</span>
    <h1>Everything that ships with AgriPulse.</h1>
    <p class="lede">Seeded before a customer types anything. A new account reads the same crops,
       indices, weather signals, decision trees and field forms on its first day.</p>
  </div>
</section>

<section class="band" style="padding-bottom:1.5rem">
  <div class="wrap"><div class="stats">{stats}</div></div>
</section>

<section class="band" style="padding-top:1.5rem">
  <div class="wrap">
    <p class="kicker">By crop</p>
    <h2 class="section">Twelve crop pages, covering all 23 seeded crops.</h2>
    <p class="big" style="max-width:64ch">Each page answers the same questions: what is in the
       catalog, which cultivars carry a plan template, what the growth stages are, which decision
       trees are written for it, and what is still missing.</p>
    <div class="tiles c4">
{croptiles}    </div>
  </div>
</section>

<section class="band tint">
  <div class="wrap">
    <p class="kicker">Across all crops</p>
    <h2 class="section">The catalogs that are not crop specific.</h2>
    <p class="big" style="max-width:64ch">Indices, weather, the rule library, field forms, and the
       operator catalogs. Every crop page links back into these.</p>
    <div class="tiles c3">
{ktiles}    </div>
  </div>
</section>
{support_block()}
""" + FOOT


def render_sections(sections) -> str:
    out = []
    for s in sections:
        out.append(f'<h3>{e(s["h"])}</h3>')
        if s.get("text"):
            out.append(f'<p>{e(s["text"])}</p>')
        if s.get("list"):
            out.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in s["list"]) + "</ul>")
        if s.get("table"):
            out.append(table(s["table"]["cols"], s["table"]["rows"]))
    return "".join(out)


def build_kb_page(k, prev, nxt, eyebrow="Catalog") -> str:
    note = (f'<div class="note"><span class="lab">Note</span><p>{e(k["note"])}</p></div>'
            if k.get("note") else "")
    depth = (f'<p style="margin-top:1rem"><span class="chip live">{e(k["depth"])}</span></p>'
             if k.get("depth") else "")

    return head(k["title"], k["lede"][:180], "kb") + f"""
<section class="hero compact">
  <img class="bg" src="img/{k["img"]}.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a> → <a href="kb.html">Knowledge Base</a></div>
    <span class="eyebrow">{e(eyebrow)}</span>
    <h1>{e(k["title"])}</h1>
    <p class="lede">{e(k["lede"])}</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
{depth}
{render_sections(k["sections"])}
{note}
  </div>
</section>
{related_block(k.get("related"))}
<section class="band tint" style="padding-top:0">
{pagenav(prev, nxt)}
</section>
""" + FOOT


def build_concepts() -> str:
    blocks = []
    for group, terms in CONCEPTS:
        blocks.append(f'<h3>{e(group)}</h3>')
        blocks.append(table(["Term", "What it means"], [[t, d] for t, d in terms]))
    return head("Key concepts", "The vocabulary the AgriPulse documentation uses.",
                "concepts") + f"""
<section class="hero compact">
  <img class="bg" src="img/p04-read.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a></div>
    <span class="eyebrow">Reference</span>
    <h1>Key concepts</h1>
    <p class="lede">One short definition each. These are the words every process page and every
       Knowledge Base page uses, so they mean the same thing everywhere on this site.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
{"".join(blocks)}
  </div>
</section>
{support_block()}
""" + FOOT


def build_support() -> str:
    sections = []
    detail = {
        "faq": ("FAQs",
                "One page of short answers, grouped the same way this site is: by process and by "
                "catalog. Each answer links to the page that covers it in full.",
                ["Questions grouped by process, so an answer sits next to its guide.",
                 "A short answer first, then a link to the full page.",
                 "English and Arabic."]),
        "ask": ("Ask the AgriPulse team",
                "A direct line to the people who build and run the platform, for the question the "
                "documentation does not answer.",
                ["A form that carries your account and farm, so we do not have to ask.",
                 "An answer by email, and the useful ones become FAQ entries.",
                 "Not a replacement for an urgent production problem."]),
        "feature": ("Request a feature",
                    "Tell us what is missing. Requests are read, answered, and the ones we take on "
                    "appear on a public list.",
                    ["What you are trying to do, and what stops you today.",
                     "How many farms or blocks it affects.",
                     "A status back: reading, planned, building, or declined with a reason."]),
    }
    for key, ico, title, text, state in SUPPORT:
        t, lede, points = detail[key]
        sections.append(f"""
    <h3 id="{key}">{e(t)} <span class="chip">{e(state)}</span></h3>
    <p>{e(lede)}</p>
    <ul>{"".join(f"<li>{e(pt)}</li>" for pt in points)}</ul>
""")
    return head("Support", "FAQs, ask the AgriPulse team, and request a feature.",
                "support") + f"""
<section class="hero compact">
  <img class="bg" src="img/p07-act.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a></div>
    <span class="eyebrow">Support</span>
    <h1>Three ways to reach us.</h1>
    <p class="lede">Beside the documentation there are three channels. All three are planned and
       none is built yet. What follows is what each one will hold.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="note"><span class="lab">Note</span>
      <p>These pages are placeholders. The design comes next. Nothing on this page sends a message
         anywhere yet.</p>
    </div>
{"".join(sections)}
  </div>
</section>
{support_block("The three channels")}
""" + FOOT


def build_404() -> str:
    return head("Page not found", "That page is not on the AgriPulse documentation site.") + """
<section class="band" style="padding-top:4rem">
  <div class="wrap narrow" style="text-align:center">
    <p class="kicker">404</p>
    <h2 class="section">That page is not here.</h2>
    <p>The address may be old, or the page may have been renamed. Start from one of these.</p>
    <div class="cards c3" style="margin-top:1.6rem; text-align:left">
      <a class="card" href="index.html"><h4>Home</h4><p>The eight processes and the crop pages</p></a>
      <a class="card" href="kb.html"><h4>Knowledge Base</h4><p>Everything that ships seeded</p></a>
      <a class="card" href="support.html"><h4>Support</h4><p>Ask us, or report what is missing</p></a>
    </div>
  </div>
</section>
""" + FOOT


def build_credits() -> str:
    rows = [[f, t, a, l] for f, t, a, l in CREDITS]
    return head("Photo credits", "Sources and licences for the photographs on this site.") + f"""
<section class="band" style="padding-top:3rem">
  <div class="wrap narrow">
    <p class="kicker">Credits</p>
    <h2 class="section">Photographs on this site</h2>
    <p>Every photograph comes from Wikimedia Commons or a public agency, under the licence listed
       here. Replace them with AgriPulse field photographs before the site goes public.</p>
    {table(["File", "Photograph", "Source", "Licence"], rows)}
    <p class="sub">Licence names: CC BY and CC BY-SA require attribution, which this page provides.
       Public domain images carry no condition. The Copernicus Sentinel-2 image is used under the
       European Union's attribution terms.</p>
    <p style="margin-top:1.4rem"><a class="btn primary" href="index.html">Back to the home page</a></p>
  </div>
</section>
""" + FOOT


def build_guide(g) -> str:
    start = "".join(f"<li>{e(x)}</li>" for x in g["start"])

    steps = []
    for st in g["steps"]:
        body = "".join(f"<li>{x}</li>" for x in st["body"])          # trusted markup
        shot = ""
        if st.get("img"):
            shot = (f'<figure class="shot-fig"><img src="img/{st["img"]}.jpg" alt="" '
                    f'loading="lazy" /><figcaption>{e(st.get("cap", ""))}</figcaption></figure>')
        note = (f'<div class="note"><span class="lab">Note</span><p>{e(st["note"])}</p></div>'
                if st.get("note") else "")
        steps.append(f"""      <div class="stage">
        <div class="badge"></div>
        <div>
          <h3>{e(st["t"])}</h3>
          <ul class="steps">{body}</ul>
          {shot}
          {note}
        </div>
      </div>
""")

    check = "".join(f"<li>{e(c)}</li>" for c in g["check"])
    proc_slug, proc_title, proc_num = g["process"]

    return head(g["title"], g["lede"][:180], "processes") + f"""
<section class="hero compact">
  <img class="bg" src="img/{g["img"]}.jpg" alt="" />
  <div class="inner">
    <div class="crumbs"><a href="index.html">Docs</a> → <a href="index.html#processes">Processes</a>
      → <a href="{proc_slug}.html">{e(proc_title)}</a></div>
    <span class="eyebrow">Guide · Process {e(proc_num)}</span>
    <h1>{e(g["title"])}</h1>
    <p class="lede">{e(g["lede"])}</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="cards c3">
      <div class="card"><h4>Who does this</h4><p>{e(g["who"])}</p></div>
      <div class="card"><h4>How long it takes</h4><p>{e(g["time"])}</p></div>
      <div class="card"><h4>Steps</h4><p>{len(g["steps"])} steps</p></div>
    </div>

    <h3>Watch it in the system</h3>
{clip_block(g["title"] + " — walkthrough", g["clip"], g.get("clip_file", ""), g.get("clip_poster", ""), g.get("clip_note", ""))}

    <h3>Before you start</h3>
    <ul>{start}</ul>
  </div>
</section>

<section class="band tint">
  <div class="wrap">
    <p class="kicker">Step by step</p>
    <h2 class="section">{e(g["title"])}</h2>
    <div class="stages" style="margin-top:1.6rem">
{"".join(steps)}    </div>

    <div class="note"><span class="lab">Check it worked</span>
      <ul style="margin:.3rem 0 0">{check}</ul>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <p class="kicker">Reference</p>
    <h2 class="section">Every field on the form</h2>
{table(g["fields"]["cols"], g["fields"]["rows"])}

    <h3>When it does not work</h3>
{table(g["mistakes"]["cols"], g["mistakes"]["rows"])}
  </div>
</section>
{related_block(g.get("next"))}
{support_block("Still stuck?")}
""" + FOOT

# ===========================================================================
# Write
# ===========================================================================

def write(name: str, content: str) -> None:
    with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"{name}  {len(content.encode('utf-8')) // 1024} KB")


def main() -> None:
    write("index.html", build_index())
    write("kb.html", build_kb_index())
    write("concepts.html", build_concepts())
    write("support.html", build_support())
    write("credits.html", build_credits())
    write("404.html", build_404())

    for g in GUIDES:
        write(f'{g["slug"]}.html', build_guide(g))

    for i, p in enumerate(PROCESSES):
        prev = (PROCESSES[i - 1]["slug"], PROCESSES[i - 1]["title"]) if i else None
        nxt = (PROCESSES[i + 1]["slug"], PROCESSES[i + 1]["title"]) if i + 1 < len(PROCESSES) else None
        write(f'{p["slug"]}.html', build_process(p, prev, nxt))

    for i, c in enumerate(CROPS):
        prev = (CROPS[i - 1]["slug"], CROPS[i - 1]["title"]) if i else None
        nxt = (CROPS[i + 1]["slug"], CROPS[i + 1]["title"]) if i + 1 < len(CROPS) else None
        write(f'{c["slug"]}.html', build_kb_page(c, prev, nxt, eyebrow="Crop"))

    for i, k in enumerate(KB):
        prev = (KB[i - 1]["slug"], KB[i - 1]["title"]) if i else None
        nxt = (KB[i + 1]["slug"], KB[i + 1]["title"]) if i + 1 < len(KB) else None
        write(f'{k["slug"]}.html', build_kb_page(k, prev, nxt))

    print(f"\n{6 + len(GUIDES) + len(PROCESSES) + len(CROPS) + len(KB)} pages written into {HERE}")


if __name__ == "__main__":
    main()
