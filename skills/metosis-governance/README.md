# Metosis Governance Skill — Installation

## Prerequisites

- ZeroClaw CLI installed
- Access to a running OASIS governance API server

## Install

```bash
zeroclaw skills install ./skills/metosis-governance
```

## Configuration

Add the governance API server to your ZeroClaw `config.toml`:

```toml
# ZeroClaw config.toml
allowed_domains = ["localhost:8000"]
```

For production deployments, replace `localhost:8000` with your governance API host:

```toml
allowed_domains = ["governance.agentcity.example.com"]
```

## Verify

After installation, verify the skill is loaded:

```bash
zeroclaw skills list
```

You should see `metosis-governance` with 10 HTTP tools:

```
metosis-governance  v0.1.0  10 tools  [governance, legislative, agentcity]
```

## Usage

See [SKILL.md](SKILL.md) for the full tool reference and governance lifecycle walkthrough.
