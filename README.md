# Dev Environment Setup — Contabo VPS

Remote terminal-only dev environment on Ubuntu (Contabo VPS), driven from Windows + WSL.

---

## 1. SSH Access (local WSL → VPS)

Generate a key in WSL Ubuntu:
```bash
ssh-keygen -t ed25519 -C "vps-key"
```

Copy it to the VPS (initial root access):
```bash
ssh-copy-id root@<contabo-ip>
```

Local SSH config (`~/.ssh/config` in WSL):
```
Host vps
    HostName <contabo-ip>
    User joshua
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
```

Test:
```bash
ssh vps
```

---

## 2. Non-root user + sudo (on VPS, as root)

```bash
adduser joshua
usermod -aG sudo joshua

mkdir -p /home/joshua/.ssh
cp ~/.ssh/authorized_keys /home/joshua/.ssh/authorized_keys
chown -R joshua:joshua /home/joshua/.ssh
chmod 700 /home/joshua/.ssh
chmod 600 /home/joshua/.ssh/authorized_keys
```

Verify `ssh joshua@<ip>` and `sudo whoami` work **before** locking root down.

Lock down `/etc/ssh/sshd_config`:
```
PermitRootLogin no
PasswordAuthentication no
```

Restart SSH (Ubuntu service is named `ssh`, not `sshd`):
```bash
sudo sshd -t          # test config syntax first
sudo systemctl restart ssh
```

---

## 3. Windows Terminal profile

Add to Windows Terminal settings JSON:
```json
{
    "name": "VPS",
    "commandline": "wsl.exe -e ssh vps",
    "startingDirectory": "%USERPROFILE%"
}
```

Uses WSL's own `ssh` + `~/.ssh/config` — keeps keys/config consistent with the rest of the Linux tooling. Test `wsl.exe -e ssh vps` in plain `cmd.exe` first if the profile misbehaves.

---

## 4. tmux (session persistence on VPS)

```bash
sudo apt install tmux -y
```

Usage:
```bash
tmux new -s work        # start session
# Ctrl-b d               # detach
tmux attach -t work      # reattach later
```

Sessions survive disconnects/laptop sleep — processes keep running.

---

## 5. Git + GitHub

```bash
git config --global user.name "Joshua Moody"
git config --global user.email "your@email.com"
```

Generate a separate SSH key on the VPS for GitHub:
```bash
ssh-keygen -t ed25519 -C "vps-github"
cat ~/.ssh/id_ed25519.pub
```
Add the public key at GitHub → Settings → SSH and GPG keys.

Test:
```bash
ssh -T git@github.com
```

New project → push to GitHub:
```bash
mkdir -p ~/projects/strongchat && cd ~/projects/strongchat
git init
echo "# strongchat" > README.md
git add . && git commit -m "init"
git branch -M main
git remote add origin git@github.com:joshuamoody2018/strongchat.git
git push -u origin main
```

---

## 6. OpenCode + OpenRouter

```bash
curl -fsSL https://opencode.ai/install | bash
```

API key:
```bash
echo 'export OPENROUTER_API_KEY="sk-or-..."' >> ~/.bashrc
source ~/.bashrc
```

Config location and exact schema **not yet confirmed** — check `opencode --help` / `opencode auth login` for the current setup flow rather than assuming a hand-written config file. (Pending: finish this step and document the working config.)

---

## 7. Neovim (LazyVim)

Install Neovim (apt version is stale):
```bash
curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
tar xzf nvim-linux-x86_64.tar.gz
sudo mv nvim-linux-x86_64 /opt/nvim
echo 'export PATH="$PATH:/opt/nvim/bin"' >> ~/.bashrc
source ~/.bashrc
```

Install LazyVim starter config:
```bash
git clone https://github.com/LazyVim/starter ~/.config/nvim
rm -rf ~/.config/nvim/.git
nvim   # auto-installs plugins on first launch, restart after
```

**Dependencies required by LazyVim (Telescope + Treesitter):**
```bash
sudo apt install fd-find ripgrep build-essential -y

# Ubuntu names the binary fdfind, not fd — symlink it
mkdir -p ~/.local/bin
ln -s $(which fdfind) ~/.local/bin/fd
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

If treesitter parsers fail to build after install:
```
:TSUpdate
```

**Basic keys:**
- `Space` alone → command menu (leader key)
- `Space ff` → find files
- `Space fg` → grep project
- `Space e` → file explorer
- `:e filename` → open file directly
- `i` insert / `Esc` exit insert / `:wq` save+quit / `:q!` quit no save

---

# 8 Pip:
sudo apt install python3-pip

## Open items
- [ ] Confirm OpenCode config schema and finish OpenRouter model setup
- [ ] Pick working model IDs per task (cheap vs. heavy) via openrouter.ai/models
