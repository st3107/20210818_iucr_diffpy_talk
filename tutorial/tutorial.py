import typing
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

from scipy.optimize import least_squares
from diffpy.utils.parsers.loaddata import loadData
from diffpy.srfit.fitbase import FitRecipe, FitContribution, Profile, FitResults
from diffpy.srfit.pdf import PDFGenerator, PDFParser
from diffpy.srfit.fitbase.parameterset import ParameterSet
from pyobjcryst import loadCrystal
from pyobjcryst.crystal import Crystal
import diffpy.srfit.pdf.characteristicfunctions

F = diffpy.srfit.pdf.characteristicfunctions


def _create_recipe(
        equation: str,
        crystals: typing.Dict[str, Crystal],
        functions: typing.Dict[str, typing.Tuple[typing.Callable, typing.List[str]]],
        profile: Profile,
        fc_name: str = "PDF"
) -> FitRecipe:
    """Create the FitRecipe object.

    Parameters
    ----------
    equation :
        The equation of G(r).
    crystals :
        A mapping from the name of variable in the equation to the crystal structure for PDF calculation.
    functions :
        A mapping from the name of variable in the equation to the python function for PDF calculation.
        The first argument of the function is the array of r, the other arguments are the parameters.
    profile :
        The data profile that contains both the metadata and the data.
    fc_name :
        The name of the FitContribution in the FitRecipe. Default "PDF".

    Returns
    -------
    A FitRecipe object.
    """
    fr = FitRecipe()
    fc = FitContribution(fc_name)
    for name, crystal in crystals.items():
        pg = PDFGenerator(name)
        pg.setStructure(crystal, periodic=True)
        fc.addProfileGenerator(pg)
    for name, (f, argnames) in functions.items():
        fc.registerFunction(f, name=name, argnames=argnames)
    fc.setEquation(equation)
    fc.setProfile(profile, xname="r", yname="G", dyname="dG")
    fr.addContribution(fc)
    return fr


def _get_tags(phase: str, param: str) -> typing.List[str]:
    """Get the tag names.

    Parameters
    ----------
    phase
    param

    Returns
    -------

    """
    return [param, phase, "{}_{}".format(phase, param)]


def _get_name(*args: str) -> str:
    """Get the name of the variable.

    Parameters
    ----------
    args

    Returns
    -------

    """
    return "_".join(args)


def _rename_par(name: str, atoms: list) -> str:
    """Rename of the name of a parameter by replacing the index of the atom in the name by the label of
    the atom and revert the order of coordinates and atom name.

    Used for the space group constrained parameters. For example, "x_0" where atom index 0 is Ni will become
    "Ni0_x" after renamed. If the name can not renamed, return the original name.

    Parameters
    ----------
    name
    atoms

    Returns
    -------

    """
    parts = name.split("_")
    np = len(parts)
    na = len(atoms)
    if np > 1 and parts[1].isdigit() and -1 < int(parts[1]) < na:
        parts[1] = atoms[int(parts[1])].name
        parts = parts[::-1]
    return "_".join(parts)


def _add_params_in_pg(recipe: FitRecipe, pg: PDFGenerator) -> None:
    """Add parameters in the PDFGenerator.

    Parameters
    ----------
    recipe
    pg

    Returns
    -------

    """
    name: str = pg.name
    recipe.addVar(
        pg.scale,
        name=_get_name(name, "scale"),
        value=0.,
        fixed=True,
        tags=_get_tags(name, "scale")
    ).boundRange(0.)
    recipe.addVar(
        pg.delta2,
        name=_get_name(name, "delta2"),
        value=0.,
        fixed=True,
        tags=_get_tags(name, "delta2")
    ).boundRange(0.)
    latpars = pg.phase.sgpars.latpars
    for par in latpars:
        recipe.addVar(
            par,
            name=_get_name(name, par.name),
            fixed=True,
            tags=_get_tags(name, "lat")
        ).boundRange(0.)
    atoms: typing.List[ParameterSet] = pg.phase.getScatterers()
    for atom in atoms:
        par = atom.Biso
        recipe.addVar(
            par,
            name=_get_name(name, atom.name, "Biso"),
            value=0.02,
            fixed=True,
            tags=_get_tags(name, "adp")
        ).boundRange(0.)
    xyzpars = pg.phase.sgpars.xyzpars
    for par in xyzpars:
        par_name = _rename_par(par.name, atoms)
        recipe.addVar(
            par,
            name=_get_name(name, par_name),
            fixed=True,
            tags=_get_tags(name, "xyz")
        )
    return


def _add_params_in_fc(
        recipe: FitRecipe,
        fc: FitContribution,
        names: typing.List[str],
        tags: typing.List[str]
) -> None:
    """Add parameters in the FitContribution.

    Parameters
    ----------
    recipe
    fc
    names
    tags

    Returns
    -------

    """
    for name in names:
        par = getattr(fc, name)
        recipe.addVar(
            par,
            value=100.,
            fixed=True,
            tags=tags
        )
    return


def _initialize_recipe(
        recipe: FitRecipe,
        functions: typing.Dict[str, typing.Tuple[typing.Callable, typing.List[str]]],
        crystals: typing.Dict[str, Crystal],
        fc_name: str = "PDF"
) -> None:
    """Initialize the FitRecipe object with variables.

    The parameters are the scale of the PDF, the delta2 parameter in the correction of correlated motions,
    the atomic displacement parameters (ADPs) of the symmetric unique atoms, the x, y, z positions of the
    symmetric unique atoms under the constraint of the symmetry and the parameters in the functions registered
    in the FitContribution.

    Parameters
    ----------
    recipe
    functions
    crystals
    fc_name

    Returns
    -------

    """
    fc: FitContribution = getattr(recipe, fc_name)
    for name, (_, argnames) in functions.items():
        _add_params_in_fc(recipe, fc, argnames[1:], tags=[name])
    for name in crystals.keys():
        pg: PDFGenerator = getattr(fc, name)
        _add_params_in_pg(recipe, pg)
    recipe.clearFitHooks()
    return


def create_recipe_from_files(
        equation: str,
        cif_files: typing.Dict[str, str],
        functions: typing.Dict[str, typing.Tuple[typing.Callable, typing.List[str]]],
        data_file: typing.Dict[str, str],
        meta_data: typing.Dict[str, typing.Union[str, int, float]] = None,
        fc_name: str = "PDF"
) -> FitRecipe:
    """Create the FitRecipe object.

    Parameters
    ----------
    equation :
        The equation of G(r).
    cif_files :
        A mapping from the name of variable in the equation to cif files of the crystal structure for PDF
        calculation.
    functions :
        A mapping from the name of variable in the equation to the python function for PDF calculation.
        The first argument of the function is the array of r, the other arguments are the parameters.
    data_file :
        The data file that be loaded into the data profile that contains both the metadata and the data.
    meta_data :
        Additional metadata to add into the data profile.
    fc_name :
        The name of the FitContribution in the FitRecipe. Default "PDF".

    Returns
    -------
    A FitRecipe object.
    """
    if meta_data is None:
        meta_data = {}
    crystals = {n: loadCrystal(f) for n, f in cif_files.items()}
    pp = PDFParser()
    pp.parseFile(data_file)
    profile = Profile()
    profile.loadParsedData(pp)
    profile.meta.update(meta_data)
    recipe = _create_recipe(equation, crystals, functions, profile, fc_name=fc_name)
    _initialize_recipe(recipe, functions, crystals, fc_name=fc_name)
    return recipe


def optimize_params(
        recipe: FitRecipe,
        steps: typing.List[typing.List[str]],
        rmin: float = None,
        rmax: float = None,
        rstep: float = None,
        print_step: bool = True,
        fc_name: str = "PDF",
        **kwargs
) -> None:
    """Optimize the parameters in the FitRecipe object using least square regression.

    Parameters
    ----------
    recipe :
        The FitRecipe object.
    steps :
        A list of lists of parameter names in the recipe. They will be free and refined one batch after another.
        Usually, the scale, lattice should be refined before the APD and XYZ.
    rmin :
        The minimum r in the range for refinement. If None, use the minimum r in the data.
    rmax :
        The maximum r in the range for refinement. If None, use the maximum r in the data.
    rstep :
        The step of r in the range for refinement. If None, use the step of r in the data.
    print_step :
        If True, print out the refinement step. Default True.
    fc_name :
        The name of the FitContribution in the FitRecipe. Default "PDF".
    kwargs :
        The kwargs for the `scipy.optimize.least_square`.

    Returns
    -------
    None.
    """
    n = len(steps)
    fc: FitContribution = getattr(recipe, fc_name)
    p: Profile = fc.profile
    p.setCalculationRange(xmin=rmin, xmax=rmax, dx=rstep)
    for step in steps:
        recipe.fix(*step)
    for i, step in enumerate(steps):
        recipe.free(*step)
        if print_step:
            print(
                "Step {} / {}: refine {}".format(
                    i + 1, n, ", ".join(recipe.getNames())
                ),
                end="\r"
            )
        least_squares(recipe.residual, recipe.getValues(), bounds=recipe.getBounds2(), **kwargs)
    return


def visualize_fits(recipe: FitRecipe, fc_name: str = "PDF") -> None:
    """Visualize the fits in the FitRecipe object.

    Parameters
    ----------
    recipe :
        The FitRecipe object.
    fc_name :
        The name of the FitContribution in the FitRecipe. Default "PDF".

    Returns
    -------
    None.
    """
    # get data
    fc = getattr(recipe, fc_name)
    r = fc.profile.x
    g = fc.profile.y
    gcalc = fc.profile.ycalc
    gdiff = g - gcalc
    diffzero = -0.8 * np.max(g) * np.ones_like(g)
    # plot figure
    _, ax = plt.subplots()
    ax.plot(r, g, 'bo', label="G(r) Data")
    ax.plot(r, gcalc, 'r-', label="G(r) Fit")
    ax.plot(r, gdiff + diffzero, 'g-', label="G(r) Diff")
    ax.plot(r, diffzero, 'k-')
    ax.set_xlabel(r"$r (\AA)$")
    ax.set_ylabel(r"$G (\AA^{-2})$")
    ax.legend(loc=1)
    plt.show()
    return


def save_results(
        recipe: FitRecipe,
        directory: str,
        file_stem: str,
        pg_names: typing.List[str] = None,
        fc_name: str = "PDF"
) -> None:
    """Save the parameters, fits and structures in the FitRecipe object.

    Parameters
    ----------
    recipe :
        The FitRecipe object.
    directory :
        The directory to output the files.
    file_stem :
        The stem of the filename.
    pg_names :
        The name of the PDFGenerators (it will also be the name of the structures) to save. If None, not to save.
    fc_name
        The name of the FitContribution in the FitRecipe. Default "PDF".
    Returns
    -------
    None.
    """
    d_path = Path(directory)
    d_path.mkdir(parents=True, exist_ok=True)
    f_path = d_path.joinpath(file_stem)
    fr = FitResults(recipe)
    fr.saveResults(str(f_path.with_suffix(".res")))
    fc: FitContribution = getattr(recipe, fc_name)
    profile: Profile = fc.profile
    profile.savetxt(str(f_path.with_suffix(".fgr")))
    if pg_names is not None:
        for pg_name in pg_names:
            pg: PDFGenerator = getattr(fc, pg_name)
            stru: Crystal = pg.stru
            cif_path = f_path.with_name(
                "{}_{}".format(f_path.stem, pg_name)
            ).with_suffix(".cif")
            with cif_path.open("w") as f:
                stru.CIFOutput(f)
    return


def export_diff_from_fgr(fgr_file: str, dst_file: str) -> None:
    """Export the difference curve in another file from a file containing x, ycalc, y, dy.

    Parameters
    ----------
    fgr_file :
        The input file containing four columns x, ycalc, y, dy.
    dst_file :
        The output file containing two columns x, y.

    Returns
    -------
    None.s
    """
    x, ycalc, y, _ = loadData(fgr_file).T
    diff = y - ycalc
    data = np.column_stack([x, diff])
    np.savetxt(dst_file, data, header="x y")
    return


def ligand_pdf(r: np.ndarray, a: float, s: float, k: float, r0: float) -> np.ndarray:
    """The Gaussian damping cosine function. Simulate the PDF of the ligand.

    Parameters
    ----------
    r :
        The array of r.
    a :
        The amplitude of the function.
    s :
        The decay rate.
    k :
        The wave vector.
    r0 :
        The zero phase r value.

    Returns
    -------
    A data array of function values.
    """
    return a * np.exp(-np.square(s * r)) * np.cos(k * (r - r0))
