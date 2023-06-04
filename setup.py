from setuptools import setup, Extension
import os
import re
import codecs
import platform
import sysconfig
from packaging.version import Version, parse
import numpy as np
import sys
import subprocess

# to publish use:
# > python setup.py sdist bdist_wheel upload
# which depends on ~/.pypirc


# This is copied from @robbuckley's fix for Panda's
# For mac, ensure extensions are built for macos 10.9 when compiling on a
# 10.9 system or above, overriding distuitls behavior which is to target
# the version that python was built for. This may be overridden by setting
# MACOSX_DEPLOYMENT_TARGET before calling setup.pcuda-comp-generalizey
if sys.platform == 'darwin':
    if 'MACOSX_DEPLOYMENT_TARGET' not in os.environ:
        current_system: Version = parse(platform.mac_ver()[0])
        python_target: Version = parse(sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET'))
        if python_target < Version('10.9') and current_system >= Version('10.9'):
            os.environ['MACOSX_DEPLOYMENT_TARGET'] = '10.9'

here = os.path.abspath(os.path.dirname(__file__))


def read(*parts):
    with codecs.open(os.path.join(here, *parts), 'r') as fp:
        return fp.read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


def find_in_path(name, path):
    """Find a file in a search path and return its full path."""
    # adapted from:
    # http://code.activestate.com/recipes/52224-find-a-file-given-a-search-path/
    for dir in path.split(os.pathsep):
        binpath = os.path.join(dir, name)
        if os.path.exists(binpath):
            return os.path.abspath(binpath)
    return None


def get_cuda_path():
    """Return a tuple with (base_cuda_directory, full_path_to_nvcc_compiler)."""
    # Inspired by https://github.com/benfred/implicit/blob/master/cuda_setup.py
    nvcc_bin = "nvcc.exe" if sys.platform == "win32" else "nvcc"

    if "CUDAHOME" in os.environ:
        cuda_home = os.environ["CUDAHOME"]
    elif "CUDA_PATH" in os.environ:
        cuda_home = os.environ["CUDA_PATH"]
    else:
        # otherwise, search the PATH for NVCC
        found_nvcc = find_in_path(nvcc_bin, os.environ["PATH"])
        if found_nvcc is None:
            print(
                "The nvcc binary could not be located in your $PATH. Either "
                "add it to your path, or set $CUDAHOME to enable CUDA.",
            )
            return None
        cuda_home = os.path.dirname(os.path.dirname(found_nvcc))
    if not os.path.exists(os.path.join(cuda_home, "include")):
        print("Failed to find cuda include directory, using /usr/local/cuda")
        cuda_home = "/usr/local/cuda"

    nvcc = os.path.join(cuda_home, "bin", nvcc_bin)
    if not os.path.exists(nvcc):
        print("Failed to find nvcc compiler in %s, trying /usr/local/cuda" % nvcc)
        cuda_home = "/usr/local/cuda"
        nvcc = os.path.join(cuda_home, "bin", nvcc_bin)

    return (cuda_home, nvcc)


def compile_cuda_module(host_args):
    libname = '_cext_gpu.lib' if sys.platform == 'win32' else 'lib_cext_gpu.a'
    lib_out = 'build/' + libname
    if not os.path.exists('build/'):
        os.makedirs('build/')

    _, nvcc = get_cuda_path()

    print("NVCC ==> ", nvcc)
    arch_flags = "-arch=sm_37 " + \
                 "-gencode=arch=compute_37,code=sm_37 " + \
                 "-gencode=arch=compute_70,code=sm_70 " + \
                 "-gencode=arch=compute_75,code=sm_75 " + \
                 "-gencode=arch=compute_75,code=compute_75"
    nvcc_command = "-allow-unsupported-compiler shap/cext/_cext_gpu.cu -lib -o {} -Xcompiler {} -I{} " \
                   "--std c++14 " \
                   "--expt-extended-lambda " \
                   "--expt-relaxed-constexpr {}".format(
                       lib_out,
                       ','.join(host_args),
                       sysconfig.get_path("include"),
                       arch_flags)
    print("Compiling cuda extension, calling nvcc with arguments:")
    print([nvcc] + nvcc_command.split(' '))
    subprocess.run([nvcc] + nvcc_command.split(' '), check=True)
    return 'build', '_cext_gpu'


def run_setup(
    *,
    with_binary,
    with_cuda,
):
    ext_modules = []
    if with_binary:
        compile_args = []
        if sys.platform == 'zos':
            compile_args.append('-qlonglong')
        if sys.platform == 'win32':
            compile_args.append('/MD')

        ext_modules.append(
            Extension('shap._cext', sources=['shap/cext/_cext.cc'],
                      include_dirs=[np.get_include()],
                      extra_compile_args=compile_args))
    if with_cuda:
        try:
            cuda_home, _ = get_cuda_path()
            if sys.platform == 'win32':
                cudart_path = cuda_home + '/lib/x64'
            else:
                cudart_path = cuda_home + '/lib64'
                compile_args.append('-fPIC')

            lib_dir, lib = compile_cuda_module(compile_args)

            ext_modules.append(
                Extension('shap._cext_gpu', sources=['shap/cext/_cext_gpu.cc'],
                          extra_compile_args=compile_args,
                          include_dirs=[np.get_include()],
                          library_dirs=[lib_dir, cudart_path],
                          libraries=[lib, 'cudart'],
                          depends=['shap/cext/_cext_gpu.cu', 'shap/cext/gpu_treeshap.h','setup.py'])
            )
        except Exception as e:
            raise Exception("Error building cuda module: " + repr(e)) from e

    extras_require = {
        'plots': [
            'matplotlib',
            'ipython'
        ],
        'others': [
            'lime',
        ],
        'docs': [
            'matplotlib',
            'ipython',
            'numpydoc',
            'sphinx_rtd_theme',
            'sphinx',
            'nbsphinx',
        ],
        'test-core': [
            "pytest",
            "pytest-mpl",
            "pytest-cov",
        ],
        'test-extras': [
            "xgboost",
            "lightgbm",
            "catboost",
            "pyspark",
            "pyod",
            "transformers",
            "torch",
            "torchvision",
            "tensorflow",
            "sentencepiece",
            "opencv-python",
        ],
    }
    extras_require['test'] = extras_require['test-core'] + extras_require['test-extras']
    extras_require['all'] = list(set(i for val in extras_require.values() for i in val))

    setup(
        name='shap',
        version=find_version("shap", "__init__.py"),
        description='A unified approach to explain the output of any machine learning model.',
        long_description="SHAP (SHapley Additive exPlanations) is a unified approach to explain "
                         "the output of " + \
                         "any machine learning model. SHAP connects game theory with local "
                         "explanations, uniting " + \
                         "several previous methods and representing the only possible consistent "
                         "and locally accurate " + \
                         "additive feature attribution method based on expectations.",
        long_description_content_type="text/markdown",
        url='http://github.com/slundberg/shap',
        author='Scott Lundberg',
        author_email='slund1@cs.washington.edu',
        license='MIT',
        packages=[
            'shap', 'shap.explainers', 'shap.explainers.other', 'shap.explainers._deep',
            'shap.plots', 'shap.plots.colors', 'shap.benchmark', 'shap.maskers', 'shap.utils',
            'shap.actions', 'shap.models'
        ],
        package_data={'shap': ['plots/resources/*', 'cext/tree_shap.h']},
        install_requires=['numpy', 'scipy', 'scikit-learn', 'pandas', 'tqdm>4.25.0',
                          'packaging>20.9', 'slicer==0.0.7', 'numba', 'cloudpickle'],
        extras_require=extras_require,
        ext_modules=ext_modules,
        classifiers=[
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX",
            "Operating System :: Unix",
            "Operating System :: MacOS",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
        ],
        zip_safe=False
        # python_requires='>3.0' we will add this at some point
    )


def try_run_setup(**kwargs):
    """ Fails gracefully when various install steps don't work.
    """

    try:
        run_setup(**kwargs)
    except Exception as e:
        print("Exception occurred during setup,", str(e))
        exc_msg = str(e).lower()

        if "cuda module" in exc_msg:
            kwargs["with_cuda"] = False
            print("WARNING: Could not compile cuda extensions.")
        elif kwargs["with_binary"]:
            kwargs["with_binary"] = False
            print("WARNING: The C extension could not be compiled, sklearn tree models not supported.")
        else:
            print("ERROR: Failed to build!")
            return

        try_run_setup(**kwargs)


# we seem to need this import guard for appveyor
if __name__ == "__main__":
    try_run_setup(
        with_binary=True,
        with_cuda=True,
    )
