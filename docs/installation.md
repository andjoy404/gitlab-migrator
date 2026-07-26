# Installation

## Requirements

- Python 3.9 or newer and `pipx`
- Git; Git LFS when migrating LFS objects
- `skopeo` only for container-registry migration
- Network access to both GitLab instances

## Install with pipx

Install pipx using the instructions for your operating system, then make sure
pipx's application directory is available to new terminal sessions:

```bash
pipx ensurepath
```

Close and reopen the terminal after running `pipx ensurepath`. On Linux, WSL2,
and macOS, reloading the current shell with `exec "$SHELL" -l` is an
alternative. On Windows, open a new PowerShell or Command Prompt window.

Public repository over HTTPS:

```bash
pipx install git+https://github.com/andjoy404/gitlab-migrator.git
```

Private repository or SSH preference:

```bash
pipx install git+ssh://git@github.com/andjoy404/gitlab-migrator.git
```

Confirm the installation:

```bash
gitlab-migrator --version
gitlab-migrator --help
```

The package uses Python's portable console-script entry point. pipx creates
`gitlab-migrator` on Linux, WSL2, and macOS, and a Windows launcher for the
same `gitlab-migrator` command on native Windows.

### Command not found

First inspect the installation and ask pipx to repair its shell configuration:

```bash
pipx list
pipx ensurepath
```

Then start a new terminal and try `gitlab-migrator --help` again.

On Linux, WSL2, and macOS, pipx normally exposes applications from
`~/.local/bin`. If that directory is still absent from `PATH`, add this line
to the startup file for your shell (for example, `~/.zshrc` on macOS or
`~/.bashrc` on Ubuntu/WSL2):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Reload the shell after editing the file:

```bash
exec "$SHELL" -l
```

On native Windows, run this in PowerShell:

```powershell
pipx ensurepath
```

Open a new PowerShell window afterward. Do not copy the Unix
`~/.local/bin` export into PowerShell; pipx adds the appropriate Windows
directory to the user `PATH`. These commands show which launcher is being
used:

```powershell
Get-Command gitlab-migrator
pipx list
```

If the command is installed but is not found after opening a new terminal,
run `pipx environment --value PIPX_BIN_DIR`, add the returned directory to
the user `Path` environment variable, and open another terminal.

WSL2 is a separate Linux environment. Install pipx and GitLab Migrator inside
WSL2 if the command will be run there; a native Windows pipx installation
does not automatically expose its applications inside WSL2, or vice versa.

## Upgrade

The package and command now share the same name:

```bash
pipx upgrade gitlab-migrator
```

For a Git installation, force a fresh install if pipx reports no newer published version:

```bash
pipx install --force git+https://github.com/andjoy404/gitlab-migrator.git
```

## Development install

Linux, WSL2, and macOS:

```bash
git clone git@github.com:andjoy404/gitlab-migrator.git
cd gitlab-migrator
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Windows PowerShell:

```powershell
git clone https://github.com/andjoy404/gitlab-migrator.git
Set-Location gitlab-migrator
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

See [configuration](configuration.md) next, or use the [Docker guide](docker.md).
