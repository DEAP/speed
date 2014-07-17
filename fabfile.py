from __future__ import division

import os
import csv
import json
import re
import time

from collections import defaultdict

from fabric.api import local, lcd, path, prefix, warn_only, quiet, task

timeit_dir = os.path.dirname(os.path.abspath(__file__))
venv_dir = timeit_dir + "/venv/"
software_dir = timeit_dir + "/software"
deap_dir = timeit_dir  + "/deap"

def grab(link):
    with lcd(software_dir+"/src"):
        local("wget {}".format(link))
    return software_dir+"/src"

def install_pypy(version):
    filename = "pypy-{}-linux64.tar.bz2".format(version)
    link = "https://bitbucket.org/pypy/pypy/downloads/{filename}".format(filename=filename)
    path = grab(link)
    local("mkdir -p {software}/pypy".format(software=software_dir))
    with lcd(software_dir+"/pypy"):
        local("tar xf {path}/{filename}".format(path=path, filename=filename))
        local("mv pypy-{version}* {version}".format(version=version))

def install_cpython(version):
    number = re.search('[1-9]+.[0-9]+.[0-9]+', version)
    if number is None:
        raise Exception("Bad version number for CPython")
    else:
        number = number.group(0)

    filename = "Python-{}.tar.xz".format(version)
    link = "http://python.org/ftp/python/{number}/{filename}".format(number=number, filename=filename)
    path = grab(link)
    with lcd(software_dir+"/src"):
        local("tar xf {filename}".format(filename=filename))

    with lcd("{software}/src/Python-{version}".format(software=software_dir, version=version)):
        local("./configure --prefix={software}/python/{version}".format(software=software_dir, version=version))
        local("make -j8")
        local("make altinstall")

def install_venv(version):
    if not os.path.lexists(software_dir + "/src/virtualenv"):
        with lcd(software_dir+"/src"):
            local("git clone https://github.com/pypa/virtualenv.git")
            local("ln -s virtualenv/virtualenv.py .")

    with lcd(timeit_dir):
        if version[:4] == "pypy":
            version = version[5:]
            local("{software}/pypy/{version}/bin/pypy {software}/src/virtualenv.py {venv}pypy-{version}".format(software=software_dir, venv=venv_dir, version=version))
        else:
            local("{software}/python/{version}/bin/python{number} {software}/src/virtualenv.py {venv}{version}".format(software=software_dir, version=version, venv=venv_dir, number=version[:3]))

def install_numpy(version):
    if version[:4] == "pypy":
        numpy = "https://bitbucket.org/pypy/numpy.git"
    else:
        numpy = "https://github.com/numpy/numpy.git"

    with prefix(". {venv}{version}/bin/activate".format(version=version, venv=venv_dir)):
        local("pip install -e git+{numpy}#egg=numpy".format(numpy=numpy))

@task
def install_dist(version):
    local("mkdir -p {software}/src".format(software=software_dir))
    if version[:4] == "pypy":
        install_pypy(version[5:])
    else:
        install_cpython(version)
    install_venv(version)
    install_numpy(version)

def clean_pull():
    if not os.path.lexists(deap_dir):
        with lcd(timeit_dir):
            local("git clone https://github.com/DEAP/deap.git deap")
    with lcd(deap_dir):
        local("find . -name \*.pyc -delete")
        local("find . -name \*.pyo -delete")
        local("find . -depth -empty -type d -exec rmdir {} \;")
        local("git clean -f -d -x") 
        local("git checkout master")
        local("git pull")

def install_deap(version, branch):
    with lcd(timeit_dir):
        with prefix(". {venv}{version}/bin/activate".format(venv=venv_dir, version=version)):
            with warn_only():   
                local("pip uninstall -y deap")
                local("find $VIRTUAL_ENV -name deap -exec rm -rf {} \;")
            with lcd(deap_dir):
                local("git checkout origin/{0}".format(branch))
                local("python setup.py install")

def create_dir(version, branch):
    with lcd(timeit_dir):
        local("mkdir -p data/{branch}/{version}".format(version=version, branch=branch))
        local("mkdir -p log/{branch}/{version}".format(version=version, branch=branch))

def get_changeset():
    with lcd(deap_dir):
        return local("git log -1 --pretty=%h", capture=True)

@task
def run_examples(version, branch, repeat):
    date = time.strftime("%Y-%m-%d")
    changeset = get_changeset() 
    results = [("Example", "Date", "Changeset", "Execution Time", "Error?")]
    folders = set()
    with prefix(". {venv}{version}/bin/activate".format(venv=venv_dir, version=version)):
        for example in open("{deap}/examples/speed.txt".format(deap=deap_dir), "r"): 
            example = example.strip("\n")
            folder, filename = example.split("/")
            with lcd("{deap}/examples/{folder}".format(deap=deap_dir, folder=folder)):
                log_folder = "{timeit}/log/{branch}/{version}/{folder}".format(timeit=timeit_dir, branch=branch, version=version, folder=folder)
                data_folder = "{timeit}/data/{branch}/{version}/{folder}".format(timeit=timeit_dir, branch=branch, version=version, folder=folder)

                if not folder in folders:
                    local("mkdir -p {folder}".format(folder=log_folder))
                    local("mkdir -p {folder}".format(folder=data_folder))
                    folders.add(folder)

                with warn_only():
                    sum_ = 0
                    for _ in range(repeat):
                        start = time.time()
                        ret = local("python {filename}.py".format(filename=filename), capture=True)
                        end = time.time()
                        if ret.failed:
                            break
                        sum_ += end - start
                    avg_time = sum_ / repeat

                    result = (example, date, changeset, avg_time, int(ret.failed))
                    results.append(result)
    
                with open("{data}/{filename}.csv".format(filename=filename, data=data_folder), "a") as fh:
                   writer = csv.writer(fh, delimiter=',')
                   writer.writerow((date, changeset, avg_time, int(ret.failed)))

                with open("{log}/{filename}.log".format(filename=filename, log=log_folder), "w") as fh:
                    if ret.failed:
                        fh.write(ret.stderr)
                    fh.write(ret)

    with open("{timeit}/data/{branch}/{version}/last_results.csv".format(timeit=timeit_dir, branch=branch, version=version), 'w') as fh:
        writer = csv.writer(fh, delimiter=',')
        writer.writerows(results)

    return results

@task    
def benchmark(version, branch, repeat=1):
    clean_pull()
    install_deap(version, branch)
    create_dir(version, branch) 
    return run_examples(version, branch, int(repeat))

@task
def sync(server):
    local("rsync -avz {timeit}/data/ {server}:/services/deap/timeit/data/".format(timeit=timeit_dir, server=server))
    local("rsync -avz {timeit}/log/ {server}:/services/deap/timeit/log/".format(timeit=timeit_dir, server=server))
    local("rsync -avz {timeit}/interpreters.js {server}:/services/deap/timeit/interpreters.js".format(timeit=timeit_dir, server=server))

@task
def run_all(branch, repeat=3):
    start = time.time()
    examples = defaultdict(list)
    versions = {}
    for version in os.listdir("{timeit}/venv".format(timeit=timeit_dir)):
        results = benchmark(version, branch, repeat=repeat)
        for result in results[1:]:
            name = result[0]
            examples[name].append([version]+list(result[1:]))

        if version[:4] == "pypy":
            versions[version] = "PyPy {}".format(version[5:])
        else:
            versions[version] = "CPython {}".format(version)
            
    with open("{timeit}/interpreters.js".format(timeit=timeit_dir), 'w') as fh:
        fh.write("var interpreter = ")
        json.dump(versions, fh)

    local("rm -rf {timeit}/data/{branch}/all".format(timeit=timeit_dir, branch=branch))
    folders = set()
    for example, results in examples.items():
        folder, filename = example.split("/")
        path = "{timeit}/data/{branch}/all/{folder}".format(timeit=timeit_dir, branch=branch, folder=folder)
        if not folder in folders:
            local("mkdir -p {path}".format(path=path))
            folders.add(folder)
            
        with open("{path}/{filename}.csv".format(path=path, filename=filename), 'w') as fh:
            writer = csv.writer(fh, delimiter=',')
            writer.writerow(("Interpreter", "Date", "Changeset", "Execution Time", "Error?"))
            writer.writerows(results)
        
    end = time.time()
    print("Total elapsed time: {time}".format(time=(end-start)))
