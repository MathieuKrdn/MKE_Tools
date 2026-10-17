"""MKE_Tools Deadline event plugin: Discord messages when a job fails, when a render finishes, and a morning recap.

The webhook is read from the MKE prefs file (set in Houdini > MK Utils > Discord Notifications), never stored here.
File Cache jobs sent from Houdini (ExtraInfo0 = node path) already notify on success from Houdini itself, so only
their failures are sent from here.
"""
import datetime
import json
import os
import urllib.request

from Deadline.Events import DeadlineEventListener
from Deadline.Scripting import RepositoryUtils

RED, GREEN, BLUE = 0xD0603F, 0x4CAF61, 0x4F86C6


def GetDeadlineEventListener():
    return MKEDiscordListener()


def CleanupDeadlineEventListener(listener):
    listener.Cleanup()


def _post(url, content, embed):
    body = json.dumps({"username": "Deadline", "content": content, "embeds": [embed]}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "MKE_Tools"})
    urllib.request.urlopen(request, timeout=15).close()


def _duration(job):
    try:
        delta = job.JobCompletedDateTime - job.JobStartedDateTime
        minutes = int(delta.TotalMinutes)
        return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"
    except Exception:
        return "?"


def job_embed(job, title, color, extra=None):
    fields = [
        {"name": "Job", "value": job.JobName, "inline": False},
        {"name": "Frames", "value": job.JobFrames or "-", "inline": True},
        {"name": "Duration", "value": _duration(job), "inline": True},
        {"name": "Tasks", "value": f"{job.JobCompletedTasks}/{job.JobTaskCount}", "inline": True},
    ]
    if job.JobExtraInfo1:
        fields.append({"name": "Scene", "value": os.path.basename(job.JobExtraInfo1), "inline": True})
    if job.JobExtraInfo0:
        fields.append({"name": "Node", "value": job.JobExtraInfo0, "inline": True})
    fields += extra or []
    return {"title": title, "color": color, "fields": fields,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


class MKEDiscordListener(DeadlineEventListener):
    def __init__(self):
        super(MKEDiscordListener, self).__init__()
        self.OnJobFinishedCallback += self.OnJobFinished
        self.OnJobFailedCallback += self.OnJobFailed
        self.OnHouseCleaningCallback += self.OnHouseCleaning

    def Cleanup(self):
        del self.OnJobFinishedCallback
        del self.OnJobFailedCallback
        del self.OnHouseCleaningCallback

    # ------------------------------------------------------------ settings
    def prefs_path(self):
        return self.GetConfigEntryWithDefault("PrefsFile", "")

    def webhook(self):
        try:
            with open(self.prefs_path(), encoding="utf-8") as f:
                return json.load(f).get("discord_webhook", "")
        except (OSError, ValueError):
            return ""

    def send(self, content, embed):
        url = self.webhook()
        if not url:
            self.LogInfo("[MKEDiscord] no webhook configured, nothing sent")
            return
        try:
            _post(url, content, embed)
        except Exception as error:
            self.LogWarning(f"[MKEDiscord] Discord unreachable: {error}")

    # ------------------------------------------------------------ events
    def OnJobFailed(self, job):
        reports = ""
        try:
            errors = RepositoryUtils.GetJobReports(job.JobId).GetErrorReports()
            if errors:
                reports = (errors[-1].ReportMessage or "").strip()[:900]
        except Exception:
            pass
        extra = [{"name": "Last error", "value": f"```{reports}```" if reports else "see Deadline Monitor", "inline": False}]
        self.send(f"❌ **{job.JobName}** failed", job_embed(job, "Deadline job failed", RED, extra))

    def OnJobFinished(self, job):
        if job.JobExtraInfo0:  # File Cache sent from Houdini: it already announced itself
            return
        self.send(f"✅ **{job.JobName}** finished ({_duration(job)})", job_embed(job, "Deadline job finished", GREEN))

    def OnHouseCleaning(self):
        """Once a day after RecapHour: what happened since yesterday evening."""
        now = datetime.datetime.now()
        if now.hour < int(self.GetConfigEntryWithDefault("RecapHour", "8")):
            return
        state_file = os.path.join(os.path.dirname(self.prefs_path()) or ".", "mke_deadline_recap.json")
        today = now.date().isoformat()
        try:
            with open(state_file, encoding="utf-8") as f:
                if json.load(f).get("last") == today:
                    return
        except (OSError, ValueError):
            pass
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"last": today}, f)
        since = now - datetime.timedelta(hours=16)
        done, failed, running = [], [], []
        for job in RepositoryUtils.GetJobs(True):
            status = job.JobStatus
            try:
                finished = job.JobCompletedDateTime
                finished = datetime.datetime(finished.Year, finished.Month, finished.Day, finished.Hour, finished.Minute)
            except Exception:
                finished = None
            if status == "Completed" and finished and finished >= since:
                done.append(f"✅ {job.JobName}  ({_duration(job)})")
            elif status == "Failed":
                failed.append(f"❌ {job.JobName}")
            elif status == "Active" and job.JobRenderingTasks:
                running.append(f"⏳ {job.JobName}  {job.JobCompletedTasks}/{job.JobTaskCount}")
        if not (done or failed or running):
            return
        lines = done + failed + running
        embed = {"title": f"Night recap: {len(done)} OK, {len(failed)} failed, {len(running)} running",
                 "description": "\n".join(lines)[:3900], "color": RED if failed else GREEN if done else BLUE,
                 "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        self.send("☀️ Deadline recap", embed)
