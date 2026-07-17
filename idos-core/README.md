# IDOS Core

Investment Decision Operating System - Core SDK and Workers.

## Installation

```bash
pip install -e idos-core/
```

## CLI Usage

```bash
# Initialize IDOS workspace
idos init

# Add a company
idos company-add MELI "MercadoLibre" "Technology"

# Show company details
idos company-show MELI

# Create an opportunity
idos opp-create MELI

# List opportunities
idos opp-list

# Transition opportunity state
idos opp-transition OPP-20260717-001 SCREENED

# Show dashboard
idos dashboard
```
