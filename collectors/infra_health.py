import os
import shutil
import subprocess


def _read_linux_memory() -> tuple[float, float, float]:
    """Retorna (total_gb, avail_gb, pct_used) em Linux via /proc/meminfo."""
    meminfo = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split(":")
            if len(parts) == 2:
                meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
    total_gb = meminfo["MemTotal"] / (1024**2)
    avail_gb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / (1024**2)
    pct_used = ((total_gb - avail_gb) / total_gb * 100) if total_gb else 0.0
    return total_gb, avail_gb, pct_used


def collect(cfg: dict) -> str:
    """Coleta saúde de disco, memória, CPU e containers Docker locais."""
    check_docker = cfg.get("check_docker", True)
    sections = []

    try:
        disk = shutil.disk_usage(os.path.abspath(os.sep))
        d_tot = disk.total / (1024**3)
        d_free = disk.free / (1024**3)
        d_pct = (disk.used / disk.total * 100) if disk.total else 0.0
        d_status = "🚨 CRÍTICO (>85%)" if d_pct > 85 else "✅ Saudável"

        res_lines = [f"* **Armazenamento:** {d_free:.1f} GB livres de {d_tot:.1f} GB ({d_pct:.1f}% em uso) — {d_status}"]

        if os.path.exists("/proc/meminfo"):
            m_tot, m_avail, m_pct = _read_linux_memory()
            m_status = "⚠️ Alerta (>85%)" if m_pct > 85 else "✅ Saudável"
            res_lines.append(
                f"* **Memória RAM:** {m_avail:.1f} GB livres de {m_tot:.1f} GB ({m_pct:.1f}% em uso) — {m_status}"
            )

        if hasattr(os, "getloadavg"):
            l1, l5, l15 = os.getloadavg()
            res_lines.append(f"* **Carga de CPU (Load Avg):** {l1:.2f} (1m), {l5:.2f} (5m), {l15:.2f} (15m)")

        if check_docker and shutil.which("docker"):
            try:
                ps_out = subprocess.check_output(
                    ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"], text=True, stderr=subprocess.DEVNULL
                ).strip().splitlines()
                tot_c = len(ps_out)
                restarting = [l.split("|")[0] for l in ps_out if "Restarting" in l]
                stopped = [l.split("|")[0] for l in ps_out if "Exited" in l]
                unhealthy = [l.split("|")[0] for l in ps_out if "unhealthy" in l]

                c_alerts = []
                if restarting:
                    c_alerts.append(f"  * 🚨 Reiniciando em loop: {', '.join(restarting)}")
                if unhealthy:
                    c_alerts.append(f"  * ⚠️ Unhealthy: {', '.join(unhealthy)}")
                if stopped:
                    c_alerts.append(f"  * ℹ️ Parados: {', '.join(stopped)}")
                if not c_alerts:
                    c_alerts.append("  * ✅ Todos os containers rodando normalmente.")

                sections.append(
                    f"* **Containers Docker:** {tot_c} totais ({tot_c - len(restarting) - len(stopped)} ativos)\n"
                    + "\n".join(c_alerts)
                )

                stats_out = subprocess.check_output(
                    ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}|{{.MemPerc}}|{{.CPUPerc}}"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip().splitlines()
                c_stats = []
                for line in stats_out:
                    parts = line.split("|")
                    if len(parts) == 4:
                        try:
                            c_stats.append((float(parts[2].replace("%", "")), parts[0], parts[1], parts[3]))
                        except ValueError:
                            pass
                c_stats.sort(reverse=True)
                if c_stats:
                    top_consumers = [
                        f"- **{n}:** {mem_u} ({p:.1f}% RAM) | CPU: {cpu}" for p, n, mem_u, cpu in c_stats[:3]
                    ]
                    sections.append("#### 🔝 Maiores Consumidores de Memória:\n" + "\n".join(top_consumers))

            except Exception as exc:
                sections.append(f"* **Containers Docker:** ⚠️ não foi possível consultar o Docker ({exc.__class__.__name__}).")

        sections.insert(1 if sections else 0, "#### 🖥️ Consumo de Recursos:\n" + "\n".join(res_lines))
        return "\n\n".join(sections)
    except Exception as exc:
        return f"⚠️ Erro ao verificar infraestrutura: {exc}"
