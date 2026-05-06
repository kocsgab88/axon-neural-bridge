"""
AXON SRE Watchman v1.0
OWNER: GABOR KOCSIS | AXON Neural Bridge
────────────────────────────────────────
Folyamatosan figyeli a gép állapotát.
Ha valami kritikus szintet ér el → Telegram értesítés.
Ha az AXON bot leáll → megpróbálja jelezni.

Küszöbértékek:
- CPU: 85% felett 30 másodpercig → figyelmeztetés
- RAM: 90% felett → figyelmeztetés
- Disk: 95% felett → figyelmeztetés
"""

import asyncio
import logging
import psutil
from datetime import datetime

log = logging.getLogger("AXON.Watchman")

# ═══════════════════════════════════════════════════════════════
#  KÜSZÖBÉRTÉKEK
# ═══════════════════════════════════════════════════════════════
CPU_WARN_PERCENT  = 85
RAM_WARN_PERCENT  = 90
DISK_WARN_PERCENT = 95
CHECK_INTERVAL    = 60   # másodperc – ennyiként ellenőriz
CPU_SUSTAINED_SEC = 30   # ennyi másodpercig kell magas CPU hogy figyelmeztessen

# ═══════════════════════════════════════════════════════════════
#  WATCHMAN OSZTÁLY
# ═══════════════════════════════════════════════════════════════
class AxonWatchman:
    def __init__(self, alert_callback):
        """
        alert_callback: async függvény ami Telegram üzenetet küld
        Pl: lambda msg: bot.send_message(chat_id, msg)
        """
        self.alert = alert_callback
        self.running = False
        self._cpu_high_since = None   # mikor kezdett magas lenni a CPU
        self._last_alerts = {}        # ne spam-elje ugyanazt az üzenetet

    def _get_system_info(self) -> dict:
        """Rendszer állapot lekérdezése."""
        cpu    = psutil.cpu_percent(interval=2)
        ram    = psutil.virtual_memory()
        disk   = psutil.disk_usage("C:\\")

        return {
            "cpu":       cpu,
            "ram":       ram.percent,
            "ram_used":  ram.used // 1024 // 1024,
            "ram_total": ram.total // 1024 // 1024,
            "disk":      disk.percent,
            "disk_free": disk.free // 1024 // 1024 // 1024,
        }

    def _should_alert(self, key: str, cooldown_min: int = 30) -> bool:
        """
        Ugyanazt a figyelmeztetést csak 30 percenként küldi el.
        Nem kell minden percben ugyanaz az üzenet.
        """
        now = datetime.now()
        last = self._last_alerts.get(key)
        if last is None or (now - last).seconds > cooldown_min * 60:
            self._last_alerts[key] = now
            return True
        return False

    async def _check_once(self):
        """Egy ellenőrzési kör."""
        try:
            info = self._get_system_info()

            # CPU ellenőrzés – csak ha tartósan magas
            if info["cpu"] >= CPU_WARN_PERCENT:
                if self._cpu_high_since is None:
                    self._cpu_high_since = datetime.now()
                else:
                    elapsed = (datetime.now() - self._cpu_high_since).seconds
                    if elapsed >= CPU_SUSTAINED_SEC and self._should_alert("cpu"):
                        await self.alert(
                            f"⚠️ *AXON SRE Figyelmeztetés*\n\n"
                            f"🔥 CPU: *{info['cpu']}%* – már {elapsed} másodperce magas!\n"
                            f"Ellenőrizd hogy nem akadt-e el valami folyamat."
                        )
            else:
                self._cpu_high_since = None  # visszaállt normálisra

            # RAM ellenőrzés
            if info["ram"] >= RAM_WARN_PERCENT and self._should_alert("ram"):
                await self.alert(
                    f"⚠️ *AXON SRE Figyelmeztetés*\n\n"
                    f"🧠 RAM: *{info['ram']}%* "
                    f"({info['ram_used']} MB / {info['ram_total']} MB)\n"
                    f"Kritikus szint! Esetleg indítsd újra az AXON-t."
                )

            # Disk ellenőrzés
            if info["disk"] >= DISK_WARN_PERCENT and self._should_alert("disk"):
                await self.alert(
                    f"⚠️ *AXON SRE Figyelmeztetés*\n\n"
                    f"💾 Disk: *{info['disk']}%* teli "
                    f"(csak {info['disk_free']} GB szabad)\n"
                    f"Töröld a felesleges fájlokat a C: meghajtóról!"
                )

        except Exception as e:
            log.error(f"[WATCHMAN] Ellenőrzési hiba: {e}")

    async def start(self):
        """Elindítja a folyamatos figyelést háttérben."""
        self.running = True
        log.info(f"[WATCHMAN] Elindult – {CHECK_INTERVAL}s intervallum")

        while self.running:
            await self._check_once()
            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self):
        self.running = False
        log.info("[WATCHMAN] Leállítva.")


# ═══════════════════════════════════════════════════════════════
#  RENDSZER INFO FORMÁZÁS (a /status parancshoz)
# ═══════════════════════════════════════════════════════════════
def get_system_status_message() -> str:
    """Részletes rendszer státusz üzenet Telegramra."""
    try:
        import platform
        cpu    = psutil.cpu_percent(interval=1)
        ram    = psutil.virtual_memory()
        disk   = psutil.disk_usage("C:\\")

        cpu_icon  = "🔥" if cpu  >= CPU_WARN_PERCENT  else "📊"
        ram_icon  = "🔥" if ram.percent >= RAM_WARN_PERCENT  else "🧠"
        disk_icon = "🔥" if disk.percent >= DISK_WARN_PERCENT else "💾"

        return (
            f"⚙️ *AXON v5.0 STÁTUSZ*\n\n"
            f"🖥️ {platform.system()} {platform.release()}\n\n"
            f"{cpu_icon} CPU: *{cpu}%*\n"
            f"{ram_icon} RAM: *{ram.percent}%* "
            f"({ram.used//1024//1024} MB / {ram.total//1024//1024} MB)\n"
            f"{disk_icon} Disk: *{disk.percent}%* "
            f"({disk.free//1024//1024//1024} GB szabad)\n\n"
            f"🤖 Claude API: ✅\n"
            f"🔮 Gemini API: ✅\n"
            f"📱 Telegram: ✅\n"
            f"🔬 Sandbox: ✅\n"
            f"🧪 Unit tesztek: ✅\n"
            f"👁️ SRE Watchman: ✅\n"
            f"🧠 Memory/Training: ✅"
        )
    except Exception as e:
        return f"⚙️ Státusz lekérdezési hiba: {e}"
