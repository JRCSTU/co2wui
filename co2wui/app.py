import atexit
import functools
import gettext
import io
import itertools
import logging
import logging.config
import multiprocessing
import os
import pickle
import random
import re
import shutil
import json
import socket
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from importlib import resources
from os import path as osp
from os.path import basename
from pathlib import Path
from stat import S_ISDIR, S_ISREG, ST_CTIME, ST_MODE
from typing import List, Union

import click
import requests
import schedula as sh
import syncing
from babel import Locale
from babel.support import Translations
from flask import (
    Flask,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask.cli import FlaskGroup
from flask_babel import Babel
from flask_session import Session
from jinja2 import Environment, PackageLoader
from ruamel import yaml
from werkzeug.utils import secure_filename

from co2mpas import __version__, dsp

_ = gettext.gettext

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# The various steps of the progress bar
progress_bar = {
    "open_input_file": 10,
    "parse_excel_file": 13,
    "output.precondition.wltp_p": 15,
    "output.calibration.wltp_h": 30,
    "output.calibration.wltp_l": 50,
    "output.prediction.nedc_h": 60,
    "output.prediction.nedc_l": 75,
    "output.prediction.wltp_h": 85,
    "output.prediction.wltp_l": 90,
    "format_report_output_data": 95,
    "write_to_excel": 99,
}

def ensure_working_folders():
    for p in (
        ("DICE_KEYS",),
        ("input",),
        ("output",),
        ("sync", "input"),
        ("sync", "output"),
    ):
        co2wui_fpath(*p).mkdir(parents=True, exist_ok=True)


def _listdir_io(*path: Union[Path, str], patterns=("*",)) -> List[Path]:
    """Only allow for excel files as input """
    folder = co2wui_fpath(*path)
    files = itertools.chain.from_iterable(folder.glob(pat) for pat in patterns)
    return [f for f in files if f.is_file()]


def listdir_inputs(
    *path: Union[Path, str], patterns=("*.[xX][lL][sS]*",)
) -> List[Path]:
    """Only allow for excel files as input """
    return _listdir_io(*path, patterns=patterns)


def input_fpath(*path: Union[Path, str]) -> Path:
    return co2wui_fpath(*path)


def listdir_outputs(
    *path: Union[Path, str], patterns=("*.[xX][lL][sS]*", "*.[zZ][iI][pP]")
) -> List[Path]:
    """Only allow for excel files as output """
    return _listdir_io(*path, patterns=patterns)


def output_fpath(*path: Union[Path, str]) -> Path:
    return co2wui_fpath(*path)


def _home_fpath() -> Path:

    if "CO2MPAS_HOME" in os.environ:
        home = Path(os.environ["CO2MPAS_HOME"])
    else:
        home = Path.home() / ".co2mpas"
    return home


@functools.lru_cache()
def co2wui_fpath(*path: Union[Path, str]) -> Path:
    return Path(_home_fpath(), *path)


@functools.lru_cache()
def port_fpath() -> Path:
    return _home_fpath() / "server.port"


@functools.lru_cache()
def conf_fpath() -> Path:
    return _home_fpath() / "conf.yaml"


@functools.lru_cache()
def enc_keys_fpath() -> Path:
    return co2wui_fpath("DICE_KEYS") / "dice.co2mpas.keys"


@functools.lru_cache()
def key_sign_fpath() -> Path:
    return co2wui_fpath("DICE_KEYS") / "sign.co2mpas.key"


def get_running_port():
    """
    Read ``~/co2mpas/server.port`` as plain text ignoring comments & check port belongs to co2wui

    :return:
        None if not found/failed to load
    """
    port = None
    lineno = 0
    try:
        #
        with open(port_fpath(), "rt") as port_file:
            for lineno, l in enumerate(port_file):
                l = l.strip()
                if not l or re.search(" *#", l):
                    continue
                port = int(l)
    except Exception as ex:
        log.debug(
            "Could not read port-file(%s)@%s due to: %s", port_fpath(), lineno, ex
        )

    ## If we have a port we check that it's served by CO2WUI
    #
    if port:
        try:
            # Check that another app is not running
            signature = ""
            resp = urllib.request.urlopen(f"http://localhost:{port}/signature")
            if resp.code == 200:
                signature = resp.read()

                if signature == b"CO2WUI":
                    return port
        except Exception as ex:
            log.debug("Could not test-bind port(%s) due to: %s", port, ex)


def save_running_port(port):
    """Save the running port in a file
    """
    from datetime import datetime

    now = datetime.now().isoformat()
    with open(port_fpath(), "wt") as port_file:
        port_file.write(f"# Launched co2wui on {now}\n{port}\n")


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        addr = s.getsockname()
        port = addr[1]
        return port


def get_summary(runid):
    """Read a summary saved file and returns it as a dict
    """
    summary = None
    if osp.exists(co2wui_fpath("output", runid, "result.dat")):

        with open(co2wui_fpath("output", runid, "result.dat"), "rb") as summary_file:
            try:
                summary = pickle.load(summary_file)
            except:
                return None

    return summary


def remove_port_file():
    if osp.exists(port_fpath()):
        os.remove(port_fpath())


def humanised(summary):
    """Return a more readable format of the summary data structure"""

    # Ugly but easier to read
    # 1st time init dict
    formatted = {"params": {}}
    for k in summary.keys():
        if k not in ("base", "id"):
            formatted["params"][k[3]] = {}

    # 2nd time fill it
    for k in summary.keys():
        if k not in ("base", "id"):
            formatted["params"][k[3]][".".join(k)] = str(round(summary[k], 3) if isinstance(summary[k], float) else summary[k])

    return formatted


def ta_enabled():
    """Return true if all conditions for TA mode are met """
    return enc_keys_fpath().exists()


def colorize(str):
    str += "<br/>"
    str = str.replace(
        ": done", ': <span style="color: green; font-weight: bold;">done</span>'
    )
    str = re.sub(r"(CO2MPAS output written into) \((.+?)\)", r"\1 (<b>\2</b>)", str)
    return str


# Multi process related functions
def log_phases(dsp):
    """Create a callback in order to log the main phases of the Co2mpas simulation"""

    def createLambda(ph, *args):
        dsp.get_node("CO2MPAS model", node_attr=None)[0]["logger"].info(ph + ": done")

    co2mpas_model = dsp.get_node("CO2MPAS model")[0]
    for k, v in co2mpas_model.dsp.data_nodes.items():
        if k.startswith("output."):
            v["callback"] = functools.partial(createLambda, k)

    additional_phase = dsp.get_node("load_inputs", "open_input_file", node_attr=None)[0]
    additional_phase["callback"] = lambda x: additional_phase["logger"].info(
        "open_input_file: done"
    )

    additional_phase = dsp.get_node("load_inputs", "parse_excel_file", node_attr=None)[
        0
    ]
    additional_phase["callback"] = lambda x: additional_phase["logger"].info(
        "parse_excel_file: done"
    )

    additional_phase = dsp.get_node(
        "make_report", "format_report_output_data", node_attr=None
    )[0]
    additional_phase["callback"] = lambda x: additional_phase["logger"].info(
        "format_report_output_data: done"
    )

    additional_phase = dsp.get_node("write", "write_to_excel", node_attr=None)[0]
    additional_phase["callback"] = lambda x: additional_phase["logger"].info(
        "write_to_excel: done"
    )

    return dsp


def register_logger(kw):
    """Record the simulation logger into the dispatcher"""

    d, logger = kw["register_core"], kw["pass_logger"]

    # Logger for CO2MPAS model
    n = d.get_node("CO2MPAS model", node_attr=None)[0]
    n["logger"] = logger

    for model, phase in [
        ["load_inputs", "open_input_file"],
        ["load_inputs", "parse_excel_file"],
        ["make_report", "format_report_output_data"],
        ["write", "write_to_excel"],
    ]:

        # Logger for open_input_file
        n = d.get_node(model, phase, node_attr=None)[0]
        n["logger"] = logger

    return d


def run_process(args, sid):
    """Run the simulation process in a thread"""

    # Pick current thread
    process = multiprocessing.current_process()
    run_id = '-'.join([sid, str(process.pid)])

    # Create output directory for this execution
    output_folder = co2wui_fpath("output", run_id)
    os.makedirs(output_folder or ".", exist_ok=True)

    # File list
    files = listdir_inputs("input")

    # Remove excluded files
    exclude_list = args.get("exclude_list").split("|")
    if exclude_list != ['']:
      excluded = list(map(int, exclude_list))
      for f in reversed(sorted(excluded)):
        del files[int(f) - 1]

    # Dump to file
    with open(
        co2wui_fpath("output", run_id, "files.dat"), "wb"
    ) as files_list:
        pickle.dump(files, files_list)

    # Dedicated logging for this run
    fileh = logging.FileHandler(
        co2wui_fpath("output", run_id, "logfile.txt"), "a"
    )
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    frmt = "%(asctime)-15s:%(levelname)5.5s:%(name)s:%(message)s"
    logging.basicConfig(level=logging.INFO, format=frmt)
    logger.addHandler(fileh)

    # Input parameters
    kwargs = {
        "output_folder": output_folder,
        "only_summary": bool(args.get("only_summary")),
        "hard_validation": bool(args.get("hard_validation")),
        "declaration_mode": bool(args.get("declaration_mode")),
        "encryption_keys": str(enc_keys_fpath()) if enc_keys_fpath().exists() else "",
        "sign_key": str(key_sign_fpath()) if bool(args.get("tamode")) else "",
        "enable_selector": False,
        "type_approval_mode": bool(args.get("tamode")),
    }

    if (conf_fpath().exists() and bool(args.get("custom_conf"))):
      kwargs["model_conf"] = conf_fpath()

    with open(
        co2wui_fpath("output", run_id, "header.dat"), "wb"
    ) as header_file:
        pickle.dump(kwargs, header_file)

    inputs = dict(
        logger=logger,
        plot_workflow=False,
        host="127.0.0.1",
        port=4999,
        cmd_flags=kwargs,
        input_files=[str(f) for f in files],
        **{sh.START: kwargs},
    )

    # Dispatcher
    d = dsp.register()

    d.add_function("pass_logger", sh.bypass, inputs=["logger"], outputs=["core_model"])
    d.add_data("core_model", function=register_logger, wait_inputs=True)

    n = d.get_node("register_core", node_attr=None)[0]
    n["filters"] = n.get("filters", [])
    n["filters"].append(log_phases)

    ret = d.dispatch(inputs, ["done", "run", "core_model"])
    with open(
        co2wui_fpath("output", run_id, "result.dat"), "wb"
    ) as summary_file:
        pickle.dump(ret["summary"], summary_file)
    return ""


def create_app(configfile=None):
    """Main flask app"""

    from . import i18n

    app = Flask(__name__)
    sess = Session()

    babel = Babel(app)
    CO2MPAS_VERSION = __version__

    hash = random.getrandbits(128)

    app.secret_key = "%032x" % hash
    app.config["SESSION_TYPE"] = "filesystem"

    sess.init_app(app)

    app.jinja_env.globals.update(humanised=humanised)

    with resources.open_text(i18n, "texts-en.yaml") as stream:
        co2wui_texts = yaml.safe_load(stream)

    with open(os.path.join(app.root_path, "VERSION")) as version_file:
        version = version_file.read().strip()
        co2wui_texts["version"] = version
        co2wui_texts["co2mpas_version"] = CO2MPAS_VERSION

    # Global variable for plot server port
    co2wui_globals = { "plot_port": None }

    @app.route("/")
    def index():

        news_text = co2wui_texts["home"]["news"]
        try:
            response = requests.get("https://dice.jrc.ec.europa.eu/sites/default/files/news/news.html")
            if response:
              news_text = response.text
        except Exception as ex:
            log.debug("Could not get news_text due to: %s", ex)

        nohints = False
        if "nohints" in request.cookies:
            nohints = True
        return render_template(
            "layout.html",
            action="dashboard",
            data={
                "breadcrumb": ["Co2mpas"],
                "props": {"active": {"run": "", "sync": "", "doc": "", "expert": ""}},
                "nohints": nohints,
                "texts": co2wui_texts,
                "globals": co2wui_globals,
                "news_text": news_text
            },
        )

    @app.route("/signature", methods=["GET"])
    def signature():
        return render_template("signature.html")

    @app.route("/run/download-template-form")
    def download_template_form():
        return render_template(
            "layout.html",
            action="template_download_form",
            data={
                "breadcrumb": ["Co2mpas", _("Download template")],
                "props": {
                    "active": {"run": "active", "sync": "", "doc": "", "expert": ""}
                },
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/run/download-template")
    def download_template():

        # Temp file name
        of = next(tempfile._get_candidate_names())

        # Input parameters
        inputs = {"output_file": of, "template_type": "input"}

        # Dispatcher
        d = dsp.register()
        ret = d.dispatch(inputs, ["template", "done"])

        # Read from file
        data = None
        with open(of, "rb") as xlsx:
            data = xlsx.read()

        # Delete files
        os.remove(of)

        # Output xls file
        iofile = io.BytesIO(data)
        iofile.seek(0)
        return send_file(
            iofile,
            attachment_filename="co2mpas-input-template.xlsx",
            as_attachment=True,
        )

    @app.route("/run/simulation-form")
    def simulation_form():

        # Create session id if it doesn't exist
        if not "sid" in session.keys():
          session["sid"] = next(tempfile._get_candidate_names())

        if ("active_pid" in session) and (session["active_pid"] is not None):
            return redirect(
                "/run/progress?layout=layout&counter=999&id="
                + str(session["active_pid"]),
                code=302,
            )

        # If configuration file exists
        conf = [conf_fpath().name] if conf_fpath().exists() else []

        inputs = [f.name for f in listdir_inputs("input")]
        return render_template(
            "layout.html",
            action="simulation_form",
            data={
                "breadcrumb": ["Co2mpas", _("Run simulation")],
                "props": {
                    "active": {"run": "active", "sync": "", "doc": "", "expert": ""}
                },
                "inputs": inputs,
                "conf": conf,
                "ta_enabled": ta_enabled(),
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/run/uploads-list")
    def uploads_list():
        inputs = [f.name for f in listdir_inputs("input")]
        return render_template(
            "ajax.html",
            action="uploads_list",
            data={
                "inputs": inputs,
                "ta_enabled": ta_enabled(),
            },
        )

    @app.route("/run/view-summary/<runid>")
    def view_summary(runid):
        """Show a modal dialog with a execution's summary formatted in a table
        """

        # We will only include the following
        # values in the summary
        keep = {
          'nedc': [
            'Declared co2 emission value',
            'Co2 emission value',
            'Co2 emission udc',
            'Co2 emission eudc',
            'Fuel consumption value',
            'Fuel consumption udc',
            'Fuel consumption eudc',
          ],
          'wltp': [
            'Declared co2 emission value',
            'Co2 emission value',
            'Co2 emission low',
            'Co2 emission medium',
            'Co2 emission high',
            'Co2 emission extra high',
            'Fuel consumption value',
            'Fuel consumption low',
            'Fuel consumption medium',
            'Fuel consumption high',
            'Fuel consumption extra high',
          ],
        }

        # Read the header containing run information
        header = {}
        with open(co2wui_fpath("output", runid, "header.dat"), "rb") as header_file:
            try:
                header = pickle.load(header_file)
            except:
                return None

        summaries = get_summary(runid)

        if summaries is not None:
            return render_template(
                "ajax.html",
                action="summary",
                title=_("Summary of your Co2mpas execution"),
                data={"thread_id": runid, "summaries": summaries, "header": header, "keep": keep},
            )
        else:
            return ""

    # Run
    @app.route("/run/simulation")
    def run_simulation():

        # Create session id if it doesn't exist
        if not "sid" in session.keys():
          session["sid"] = next(tempfile._get_candidate_names())

        process = multiprocessing.Process(target=run_process, args=(request.args,session["sid"],))
        process.start()
        id = process.pid
        session["active_pid"] = str(id)
        return redirect(
            "/run/progress?layout=layout&counter=0&id=" + str(process.pid), code=302
        )

    @app.route("/run/progress")
    def run_progress():

        # Flags
        started = False
        done = False
        stopped = True if request.args.get("stopped") else False

        # Num of files processed up to now
        num_processed = 0

        # Process id
        process_id = request.args.get("id")
        if (process_id is None):
            return redirect("/run/simulation-form", code=302,)
        run_id = '-'.join([session["sid"], process_id])

        # Wait counter... if not started after X then error.
        # This is required due to a latency when launching a new
        # process
        counter = request.args.get("counter")
        counter = int(counter) + 1
        layout = request.args.get("layout")

        # Read the list of input files
        files = []
        if osp.exists(co2wui_fpath("output", run_id, "files.dat")):
            started = True
            with open(
                co2wui_fpath("output", run_id, "files.dat"), "rb"
            ) as files_list:
                try:
                    files = pickle.load(files_list)
                except:
                    return None

        # Read the header containing run information
        header = {}
        if osp.exists(co2wui_fpath("output", run_id, "header.dat")):
            with open(
                co2wui_fpath("output", run_id, "header.dat"), "rb"
            ) as header_file:
                try:
                    header = pickle.load(header_file)
                except:
                    return None

        # Default page status
        page = "run_progress"

        # Simulation is "done" if there's a result file
        if osp.exists(co2wui_fpath("output", run_id, "result.dat")):
            done = True
            page = "run_complete"
            session["active_pid"] = None

        # Get the summary of the execution (if ready)
        summary = get_summary(run_id)
        result = "KO" if (summary is None or not summary or len(summary[0].keys()) <= 2) else "OK"

        # Result is KO if not started and counter > 1
        if not started and counter > 1:
            result = "KO"
            page = "run_complete"
            session["active_pid"] = None

        # Check that the process is still running
        active_processes = multiprocessing.active_children()
        alive = False
        for p in active_processes:
            if str(p.pid) == process_id:
                alive = True

        if not done and not alive:
            result = "KO"
            page = "run_complete"
            session["active_pid"] = None

        # Get the log file
        log = ""
        loglines = []
        if osp.exists(co2wui_fpath("output", run_id, "logfile.txt")):
            with open(co2wui_fpath("output", run_id, "logfile.txt")) as f:
                loglines = f.readlines()
        else:
            loglines = ["Waiting for data..."]

        # Collect log, exclude web server info and colorize
        for logline in loglines:
            if logline.startswith("CO2MPAS output written into"):
                num_processed += 1
            if not re.search("- INFO -", logline):
                log += colorize(logline)

        # If simulation is stopped the log is not interesting
        if stopped:
            loglines = ["Simulation stopped."]

        # Collect data related to execution phases
        phases = [
            logline.replace(": done", "").rstrip()
            for logline in loglines
            if ": done" in logline
        ]

        # Collect result files
        results = []
        if not (summary is None or not summary or len(summary[0].keys()) <= 2):
            output_files = [f.name for f in listdir_outputs("output", run_id)]
            results.append({"name": run_id, "files": output_files})

        # Render page progress/complete
        return render_template(
            "layout.html" if layout == "layout" else "ajax.html",
            action=page,
            data={
                "breadcrumb": ["Co2mpas", _("Run simulation")],
                "props": {
                    "active": {"run": "active", "sync": "", "doc": "", "expert": ""}
                },
                "process_id": process_id,
                "run_id": run_id,
                "log": log,
                "result": result,
                "stopped": stopped,
                "counter": counter,
                "texts": co2wui_texts,
                "globals": co2wui_globals,
                "progress": (
                    (num_processed * (100 / int(round(len(files)))))
                    + int(round((progress_bar[phases[len(phases) - 1]] / len(files))))
                )
                if (len(phases)) > 0
                else 0,
                "summary": summary[0] if summary else None,
                "results": results if results is not None else None,
                "header": header,
            },
        )

    @app.route("/run/stop-simulation/<process_id>", methods=["GET"])
    def stop_simulation(process_id):
        # Check that the process is still running
        active_processes = multiprocessing.active_children()
        for p in active_processes:
            if str(p.pid) == process_id:
                p.terminate()
                time.sleep(1)

        return redirect(
            "/run/progress?layout=layout&stopped=1&counter=999&id=" + str(process_id),
            code=302,
        )

    @app.route("/run/add-file", methods=["POST"])
    def add_file():
        f = request.files['files[]']
        f.save(str(co2wui_fpath("input", secure_filename(f.filename))))
        files = {"file": f.read()}
        return json.dumps({"files": {"name": f.filename}})

    @app.route("/run/delete-file", methods=["GET"])
    def delete_file():
        fn = request.args.get("fn")
        inputs = listdir_inputs("input")
        inputs[int(fn) - 1].unlink()
        return redirect("/run/simulation-form", code=302)

    @app.route("/run/delete-all", methods=["GET"])
    def delete_all():
        inputs = listdir_inputs("input")
        for f in inputs:
          f.unlink()
        return redirect("/run/simulation-form", code=302)

    @app.route("/run/view-results")
    def view_results():

        dirpath = "output"
        entries = (
            co2wui_fpath(dirpath, fn) for fn in os.listdir(co2wui_fpath(dirpath))
        )
        entries = ((os.stat(path), path) for path in entries)
        entries = (
            (stat[ST_CTIME], path) for stat, path in entries if S_ISDIR(stat[ST_MODE])
        )

        results = []
        for cdate, path in sorted(entries):
            dirname = osp.basename(path)
            output_files = [f.name for f in listdir_outputs("output", dirname)]
            summary = get_summary(dirname)
            outcome = "KO" if (summary is None or not summary or len(summary[0].keys()) <= 2) else "OK"
            results.append(
                {
                    "datetime": time.ctime(cdate),
                    "name": dirname,
                    "files": output_files,
                    "outcome": outcome,
                }
            )

        running = False
        if ("active_pid" in session) and (session["active_pid"] is not None):
            running = True

        return render_template(
            "layout.html",
            action="view_results",
            data={
                "breadcrumb": ["Co2mpas", _("View results")],
                "props": {
                    "active": {"run": "active", "sync": "", "doc": "", "expert": ""}
                },
                "results": reversed(results),
                "running": running,
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/run/download-result/<runid>/<fnum>")
    def download_result(runid, fnum):

        files = listdir_outputs("output", runid)
        rf = files[int(fnum) - 1]

        # Read from file
        data = None
        with open(rf, "rb") as result:
            data = result.read()

        # Output xls file
        iofile = io.BytesIO(data)
        iofile.seek(0)
        return send_file(
            iofile, attachment_filename=files[int(fnum) - 1].name, as_attachment=True
        )

    @app.route("/run/download-all/<runid>")
    def download_all(runid):

        of = next(tempfile._get_candidate_names())
        co2wui_fpath(of).mkdir(parents=True, exist_ok=True)

        # Create zip archive on the of all the result
        zip_subdir = of
        iofile = io.BytesIO()
        zf = zipfile.ZipFile(iofile, mode="w", compression=zipfile.ZIP_DEFLATED)

        files = listdir_outputs("output", runid)

        # Adds demo files to archive
        for f in files:
            # Add file, at correct path
            zf.write(osp.abspath(osp.join(of, f)), basename(f))

        # Close archive
        zf.close()

        # Remove temporary files
        shutil.rmtree(co2wui_fpath(of))

        # Output zip file
        iofile.seek(0)
        return send_file(
            iofile, attachment_filename="co2mpas-result-" + runid + ".zip", as_attachment=True
        )

    @app.route("/run/delete-results", methods=["POST"])
    def delete_results():

        for k in request.form.keys():
            found = re.match(r"^select\-(.+?\-[0-9]+)$", k)
            if found:
                runid = found.group(1)
                shutil.rmtree(co2wui_fpath("output", runid))

        return redirect("/run/view-results", code=302)

    @app.route("/run/download-log/<runid>")
    def download_log(runid):

        rf = co2wui_fpath("output", runid, "logfile.txt")

        # Read from file
        data = None
        with open(rf, "rb") as xlsx:
            data = xlsx.read()

        # Output xls file
        iofile = io.BytesIO(data)
        iofile.seek(0)
        return send_file(iofile, attachment_filename="logfile.txt", as_attachment=True)

    @app.route("/sync/template-form")
    def sync_template_form():
        return render_template(
            "layout.html",
            action="synchronisation_template_form",
            data={
                "breadcrumb": ["Co2mpas", _("Data synchronisation")],
                "props": {
                    "active": {"run": "", "sync": "active", "doc": "", "expert": ""}
                },
                "texts": co2wui_texts,
                "globals": co2wui_globals,
                "title": "Data synchronisation",
            },
        )

    @app.route("/sync/template-download")
    def sync_template_download():

        # Parameters from request
        cycle_type = request.args.get("cycle")
        gear_box_type = request.args.get("gearbox")
        wltp_class = request.args.get("wltpclass")

        # Output temp file
        output_file = next(tempfile._get_candidate_names()) + ".xlsx"

        # Generate template
        import pandas as pd
        from co2mpas.core.model.physical import dsp

        theoretical = sh.selector(
            ["times", "velocities"],
            dsp(
                inputs=dict(
                    cycle_type=cycle_type.upper(),
                    gear_box_type=gear_box_type,
                    wltp_class=wltp_class,
                    downscale_factor=0,
                ),
                outputs=["times", "velocities"],
                shrink=True,
            ),
        )
        base = dict.fromkeys(
            (
                "times",
                "velocities",
                "target gears",
                "engine_speeds_out",
                "engine_coolant_temperatures",
                "co2_normalization_references",
                "alternator_currents",
                "battery_currents",
                "target fuel_consumptions",
                "target co2_emissions",
                "target engine_powers_out",
            ),
            [],
        )
        data = dict(theoretical=theoretical, dyno=base, obd=base)

        with pd.ExcelWriter(output_file) as writer:
            for k, v in data.items():
                pd.DataFrame(v).to_excel(writer, k, index=False)

        # Read from generated file
        data = None
        with open(output_file, "rb") as xlsx:
            data = xlsx.read()

        # Delete files
        os.remove(output_file)

        # Output xls file
        iofile = io.BytesIO(data)
        iofile.seek(0)
        return send_file(
            iofile, attachment_filename="datasync.xlsx", as_attachment=True
        )

    @app.route("/sync/synchronisation-form")
    def synchronisation_form():
        inputs = [f.name for f in listdir_inputs("sync", "input")]
        return render_template(
            "layout.html",
            action="synchronisation_form",
            data={
                "breadcrumb": ["Co2mpas", _("Run synchronisation")],
                "props": {
                    "active": {"run": "", "sync": "active", "doc": "", "expert": ""}
                },
                "interpolation_methods": [
                    "linear",
                    "nearest",
                    "zero",
                    "slinear",
                    "quadratic",
                    "cubic",
                    "pchip",
                    "akima",
                    "integral",
                    "polynomial0",
                    "polynomial1",
                    "polynomial2",
                    "polynomial3",
                    "polynomial4",
                    "spline5",
                    "spline7",
                    "spline9",
                ],
                "timestamp": time.time(),
                "inputs": inputs,
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/sync/add-sync-file", methods=["POST"])
    def add_sync_file():
        for f in listdir_inputs("sync", "input"):
            f.unlink()

        f = request.files["file"]
        f.save(str(input_fpath("sync", "input") / secure_filename(f.filename)))
        return redirect("/sync/synchronisation-form", code=302)

    @app.route("/sync/run-synchronisation", methods=["POST"])
    def run_synchronisation():

        # Dedicated logging for this run
        fileh = logging.FileHandler(co2wui_fpath("sync", "logfile.txt"), "w")
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        frmt = "%(asctime)-15s:%(levelname)5.5s:%(name)s:%(message)s"
        logging.basicConfig(level=logging.INFO, format=frmt)
        logger.addHandler(fileh)

        # Input file
        inputs = listdir_inputs("sync", "input")
        input_file = str(inputs[0])

        # Output file
        output_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = co2wui_fpath("sync", "output", output_name + ".sync.xlsx")

        # Remove old output files
        previous = listdir_outputs("sync", "output")
        for f in previous:
            os.remove(str(f))

        # Arguments
        kwargs = {
            "x_label": request.form.get("x_label")
            if request.form.get("x_label")
            else "times",
            "y_label": request.form.get("y_label")
            if request.form.get("y_label")
            else "velocities",
            "interpolation_method": request.form.get("interpolation_method"),
            "header": request.form.get("header"),
            "reference_name": request.form.get("reference_name")
            if request.form.get("reference_name")
            else "theoretical",
        }
        kwargs = {k: v for k, v in kwargs.items() if v}

        try:

            # Dispatcher
            _process = sh.SubDispatch(syncing.dsp, ["written"], output_type="value")
            ret = _process(
                dict(input_fpath=input_file, output_fpath=str(output_file), **kwargs)
            )
            fileh.close()
            logger.removeHandler(fileh)
            return "OK"

        except Exception as e:
            logger.error(_("Synchronisation failed: ") + str(e))
            fileh.close()
            logger.removeHandler(fileh)
            return "KO"

    @app.route("/sync/delete-file", methods=["GET"])
    def delete_sync_file():
        for f in listdir_inputs("sync", "input"):
            f.unlink()

        return redirect("/sync/synchronisation-form", code=302)

    @app.route("/sync/load-log", methods=["GET"])
    def load_sync_log():
        fpath = co2wui_fpath("sync", "logfile.txt")
        with open(fpath) as f:
            loglines = f.readlines()

        log = ""
        for logline in loglines:
            log += logline

        return log

    @app.route("/sync/download-result/<timestr>")
    def sync_download_result(timestr):
        synced = str(listdir_outputs("sync", "output")[0])
        synced_name = os.path.basename(synced)
        return send_file(synced, attachment_filename=synced_name, as_attachment=True)

    @app.route("/demo/download-demo-form")
    def download_demo_form():
        return render_template(
            "layout.html",
            action="demo_download_form",
            data={
                "breadcrumb": ["Co2mpas", _("Download demo")],
                "props": {
                    "active": {"run": "active", "sync": "", "doc": "", "expert": ""}
                },
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    # Demo/download
    @app.route("/demo/download")
    def demo_download():

        # Temporary output folder
        of = next(tempfile._get_candidate_names())

        # Input parameters
        inputs = {"output_folder": of}

        # Dispatcher
        d = dsp.register()
        ret = d.dispatch(inputs, ["demo", "done"])

        # List of demo files created
        demofiles = [f for f in os.listdir(of) if osp.isfile(osp.join(of, f))]

        # Create zip archive on the fly
        zip_subdir = of
        iofile = io.BytesIO()
        zf = zipfile.ZipFile(iofile, mode="w", compression=zipfile.ZIP_DEFLATED)

        # Adds demo files to archive
        for f in demofiles:
            # Add file, at correct path
            zf.write(osp.abspath(osp.join(of, f)), f)

        # Close archive
        zf.close()

        # Remove temporary files
        shutil.rmtree(of)

        # Output zip file
        iofile.seek(0)
        return send_file(
            iofile, attachment_filename="co2mpas-demo.zip", as_attachment=True
        )

    @app.route("/plot/launched")
    def plot_launched():
        if (not co2wui_globals["plot_port"]):
          co2wui_globals["plot_port"] = get_free_port()

        return render_template(
            "layout.html",
            action="launch_plot",
            data={
                "breadcrumb": ["Co2mpas", "Plot launched"],
                "props": {
                    "active": {"run": "", "sync": "", "doc": "", "expert": "active"}
                },
                "title": "Plot launched",
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/plot/model-graph")
    def plot_model_graph():
        """
        CLUDGE to launch plots-server from this flask server.
        
        Flask's startup cmd sets `FLASK_RUN_FROM_CLI` env-var to ``'true'``, but
        but then :meth:`app.__init__()` will prevent launching a another flask server,
        with this warning::

            Silently ignoring app.run() because the application is run 
            from the flask command line executable.  

        We abuse this variable to store the port (and stop it from being ``'true'``).
        """

        port = os.environ.get("FLASK_RUN_FROM_CLI")
        try:
            port = int(port)
            # Plots-server had already been launched.
        except Exception as ex:
            port = co2wui_globals["plot_port"]
            log.debug(
                "Expected failure parsing FLASK_RUN_FROM_CLI env-var as port-number"
                " due to : %s\n  Will now start plots-server in %s...",
                ex,
                port,
            )
            os.environ["FLASK_RUN_FROM_CLI"] = str(port)
            dsp(
                dict(
                    plot_model=True, cache_folder="cache", host="127.0.0.1", port=port
                ),
                ["plot", "done"],
            )

        ## FIXME: render this as a link in "Show model graph" page.
        return ''

    @app.route("/conf/configuration-form")
    def configuration_form():

        files = [conf_fpath().name] if conf_fpath().exists() else []

        return render_template(
            "layout.html",
            action="configuration_form",
            data={
                "breadcrumb": ["Co2mpas", _("Physical model configuration file")],
                "props": {
                    "active": {
                        "run": "",
                        "sync": "active",
                        "doc": "",
                        "expert": "active",
                    }
                },
                "timestamp": time.time(),
                "title": "Physical model configuration file",
                "inputs": files,
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/conf/add-conf-file", methods=["POST"])
    def add_conf_file():
        fpath = conf_fpath()
        if fpath.exists():
            fpath.unlink()

        f = request.files["file"]
        f.save(str(fpath))
        return redirect("/conf/configuration-form", code=302)

    @app.route("/conf/delete-file", methods=["GET"])
    def delete_conf_file():
        fpath = conf_fpath()
        fpath.unlink()
        return redirect("/conf/configuration-form", code=302)

    @app.route("/not-implemented")
    def not_implemented():
        return render_template(
            "layout.html",
            action="generic_message",
            data={
                "breadcrumb": ["Co2mpas", _("Feature not implemented")],
                "props": {"active": {"run": "", "sync": "", "doc": "", "expert": ""}},
                "title": "Feature not implemented",
                "message": "Please refer to future versions of the application or contact xxxxxxx@xxxxxx.europa.eu for information.",
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    @app.route("/conf/template")
    def conf_template():

        # Temp file name
        of = next(tempfile._get_candidate_names())

        # Input parameters
        inputs = {"output_file": of}

        # Dispatcher
        d = dsp.register()
        ret = d.dispatch(inputs, ["conf", "done"])

        # Read from file
        data = None
        with open(of, "rb") as conf:
            data = conf.read()

        # Delete files
        os.remove(of)

        # Output xls file
        iofile = io.BytesIO(data)
        iofile.seek(0)
        return send_file(
            iofile,
            attachment_filename="conf.yaml",
            as_attachment=True,
        )

    # Conf/download
    @app.route("/conf/download/<timestr>")
    def conf_download(timestr):
        of = conf_fpath()

        return send_file(of.open("rb"), attachment_filename=of.name, as_attachment=True)

    @app.route("/contact-us")
    def contact_us():
        return render_template(
            "layout.html",
            action="contact_us",
            data={
                "breadcrumb": ["Co2mpas", "Contact us"],
                "props": {
                    "active": {"run": "", "sync": "", "doc": "active", "expert": ""}
                },
                "title": "Contact us",
                "texts": co2wui_texts,
                "globals": co2wui_globals,
            },
        )

    return app


def app_banner(port: int, was_app_running: bool):
    from textwrap import dedent

    return dedent(
        f"""\
        Co2mpas GUI application {"was already" if was_app_running else "is now"} running on port {port}.
        A browser should have been automatically launched with the correct address
        If you aren't redirected automatically, please point your browser to:
            http://localhost:{port}"""
    )


@click.group(cls=FlaskGroup, create_app=create_app)
def cli():
    """Launch script for the Co2gui application & browser window."""
    # Bypass our friend flask cli in order to set the port
    # FIXME: read port from cli/configs
    ensure_working_folders()
    port = get_running_port()
    was_app_running = port is not None

    if was_app_running:
        os.environ["FLASK_RUN_PORT"] = str(port)
        print(app_banner(port, was_app_running))
        webbrowser.open(f"http://localhost:{port}")

        exit()

    port = get_free_port() or 8999
    if port:
        os.environ["FLASK_RUN_PORT"] = str(port)

        save_running_port(os.environ["FLASK_RUN_PORT"])
        atexit.register(remove_port_file)

        print(app_banner(port, was_app_running))
        webbrowser.open(f"http://localhost:{port}")


## Hide Flask's startup warning if not used behind a separate WSGI server.
# From: https://gist.github.com/jerblack/735b9953ba1ab6234abb43174210d356
#
fcli = sys.modules["flask.cli"]
fcli.show_server_banner = lambda *x: None
