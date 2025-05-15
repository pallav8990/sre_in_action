# SREHubApp Developer Workspace Setup Guide

This guide will help you set up your local development environment for contributing to **SREHubApp** using a RHEL virtual machine.

---

## 1. Prerequisites

- VM created via VMware (RHEL 8 or 9 recommended)
- Internet access inside the VM
- Basic understanding of terminal and Git

---

## 2. Install Python 3.11 on RHEL using yum (via EPEL + Deadsnakes or custom repo)

Enable required repos:

```bash
sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel wget make epel-release
sudo yum install -y python3.11 python3.11-devel python3.11-pip
```

> Verify:
```bash
python3.11 --version
pip3.11 --version
```

---

## 3. Install Poetry via pip

```bash
pip3.11 install poetry --user
```

Ensure Poetry is in your shell path:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

---

## 4. Set Poetry Configuration for Private Sources (if needed)

```bash
poetry config http-basic.<your-repo-name> <username> <password>
```

Or set credentials using `PIP_CONFIG_FILE` or `.netrc` as per org policy.

---

## 5. Clone the Repository

```bash
git clone https://github.com/<your-org>/srehubapp.git
cd srehubapp
```

---

## 6. Install Dependencies via Poetry

```bash
poetry env use python3.11
poetry install
```

---

## 7. Set Up Environment Variables

Create a `.env` file in the root directory:

```ini
# .env
LOG_LEVEL=DEBUG
SSO_SECRET_KEY=your_sso_secret
EXTERNAL_API_KEY=your_api_key
```

> Optionally export variables in `~/.bashrc` if preferred:
```bash
export LOG_LEVEL=DEBUG
export SSO_SECRET_KEY=your_sso_secret
```

---

## 8. Run the Application

```bash
poetry run python app.py
```

Flask will start on [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 9. (Optional) Run Tests

```bash
poetry run pytest
```

---

## 10. Useful Commands

| Command | Description |
|--------|-------------|
| `poetry install` | Install dependencies |
| `poetry shell` | Enter Poetry-managed virtual env |
| `poetry run <cmd>` | Run command inside env |
| `poetry add <pkg>` | Add new package |
| `poetry update` | Update packages |
| `poetry env info` | Debug env issues |