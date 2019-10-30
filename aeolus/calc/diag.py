"""Some commonly used diagnostics in atmospheric science."""
import iris

import numpy as np

from .stats import spatial
from ..const import init_const
from ..exceptions import ArgumentError


__all__ = (
    "ghe_norm",
    "heat_redist_eff",
    "minmaxdiff",
    "sfc_net_energy",
    "sfc_water_balance",
    "region_mean_diff",
    "toa_cloud_radiative_effect",
    "toa_eff_temp",
    "toa_net_energy",
    "total_precip",
)


def toa_cloud_radiative_effect(cubelist, kind):
    """
    Calculate domain-average TOA cloud radiative effect (CRE).

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes
    kind: str
        Shortwave ('sw'), longwave ('lw'), or 'total' CRE

    Returns
    -------
    iris.cube.Cube
        Cube of CRE with reduced dimensions.
    """
    name = f"toa_cloud_radiative_effect_{kind}"
    if kind == "sw":
        all_sky = "m01s01i208"
        clr_sky = "m01s01i209"
    elif kind == "lw":
        all_sky = "m01s02i205"
        clr_sky = "m01s02i206"
    elif kind == "total":
        sw = toa_cloud_radiative_effect(cubelist, "sw")
        lw = toa_cloud_radiative_effect(cubelist, "lw")
        cre = sw + lw
        cre.rename(name)
        return cre

    cube_clr = spatial(cubelist.extract_strict(iris.AttributeConstraint(STASH=clr_sky)), "mean")
    cube_all = spatial(cubelist.extract_strict(iris.AttributeConstraint(STASH=all_sky)), "mean")
    cre = cube_clr - cube_all
    cre.rename(name)
    return cre


def toa_net_energy(cubelist):
    """
    Calculate domain-average TOA energy flux.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Cube with reduced dimensions.
    """
    terms = cubelist.extract(
        ["toa_incoming_shortwave_flux", "toa_outgoing_shortwave_flux", "toa_outgoing_longwave_flux"]
    )
    assert len(terms) == 3, f"Error when extracting TOA energy fluxes from\n{cubelist}"
    terms_ave = []
    for cube in terms:
        terms_ave.append(spatial(cube, "mean"))
    toa_net = terms_ave[0] - terms_ave[1] - terms_ave[2]
    toa_net.rename("toa_net_radiative_flux")
    return toa_net


def sfc_net_energy(cubelist):
    """
    Calculate domain-average surface energy flux.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Cube with reduced dimensions.
    """
    terms = cubelist.extract(
        [
            "surface_downwelling_shortwave_flux_in_air",
            "upwelling_shortwave_flux_in_air",
            "surface_downwelling_longwave_flux_in_air",
            "upwelling_longwave_flux_in_air",
            "surface_upward_sensible_heat_flux",
            "surface_upward_latent_heat_flux",
        ]
    )
    assert len(terms) == 6, f"Error when extracting SFC energy fluxes from\n{cubelist}"
    terms_ave = []
    for cube in terms:
        terms_ave.append(spatial(cube, "mean"))
    sfc_net = (
        terms_ave[0] - terms_ave[1] + terms_ave[2] - terms_ave[3] - terms_ave[4] - terms_ave[5]
    )
    sfc_net.rename("surface_net_energy_flux")
    return sfc_net


def sfc_water_balance(cubelist):
    """
    Calculate domain-average precipitation minus evaporation.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Cube with reduced dimensions.
    """
    terms = cubelist.extract(["precipitation_flux", "surface_upward_water_flux"])
    terms_ave = []
    for cube in terms:
        terms_ave.append(spatial(cube, "mean"))
    net = terms_ave[0] - terms_ave[1]
    net.rename("surface_net_water_flux")
    return net


def total_precip(cubelist, ptype=None):
    """
    Calculate total precipitation flux [mm day^-1].

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    ptype: str, optional
        Precipitation type (stra|conv).

    Returns
    -------
    iris.cube.Cube
        Sum of cubes of precipitation with units converted to mm per day.
    """
    conv = ["convective_rainfall_flux", "convective_snowfall_flux"]
    stra = ["stratiform_rainfall_flux", "stratiform_snowfall_flux"]
    if ptype is None:
        varnames = stra + conv
    elif ptype == "stra":
        varnames = stra
    elif ptype == "conv":
        varnames = conv
    else:
        raise ArgumentError(f"Unknown ptype={ptype}")
    tot_precip = cubelist.extract_strict(varnames[0]).copy()
    for varname in varnames[1:]:
        try:
            tot_precip += cubelist.extract_strict(varname)
        except iris.exceptions.ConstraintMismatchError:
            pass
    tot_precip /= iris.coords.AuxCoord(1000, units="kg m-3")
    tot_precip.convert_units("mm day-1")
    tot_precip.rename("total_precipitation_flux")
    return tot_precip


def heat_redist_eff(cubelist, region_a, region_b):
    r"""
    Heat redistribution efficiency (Leconte et al. 2013).

    .. math::

        \eta=\frac{OLR_{TOA,night}}{OLR_{TOA,day}}

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    region_a: aeolus.region.Region
        First region (usually nightside).
    region_b: aeolus.region.Region
        Second region (usually dayside).

    Returns
    -------
    iris.cube.Cube
        Eta parameter.
    """
    toa_olr = cubelist.extract_strict("toa_outgoing_longwave_flux")
    toa_olr_a = spatial(toa_olr.extract(region_a.constraint), "mean")
    toa_olr_b = spatial(toa_olr.extract(region_b.constraint), "mean")
    eta = toa_olr_a / toa_olr_b
    eta.rename("heat_redistribution_efficiency")
    return eta


def minmaxdiff(cubelist, name):
    """
    Spatial maximum minus spatial minimum for a given cube.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    name: str
        Cube name.

    Returns
    -------
    iris.cube.Cube
        Difference between the extrema.
    """
    _min = spatial(cubelist.extract_strict(name), "min")
    _max = spatial(cubelist.extract_strict(name), "max")
    diff = _max - _min
    diff.rename(f"{name}_difference")
    return diff


def region_mean_diff(cubelist, name, region_a, region_b):
    """
    Difference between averages over two regions for a given cube.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    name: str
        Cube name.
    region_a: aeolus.region.Region
        First region.
    region_b: aeolus.region.Region
        Second region.

    Returns
    -------
    iris.cube.Cube
        Difference between the region averages.
    """
    mean_a = spatial(cubelist.extract_strict(name).extract(region_a.constraint), "mean")
    mean_b = spatial(cubelist.extract_strict(name).extract(region_b.constraint), "mean")
    diff = mean_a - mean_b
    diff.rename(f"{name}_mean_diff_{region_a}_{region_b}")
    return diff


def toa_eff_temp(cubelist):
    """
    Calculate effective temperature from TOA OLR.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
    """
    toa_olr = cubelist.extract_strict("toa_outgoing_longwave_flux")
    sbc = init_const().stefan_boltzmann.asc
    t_eff = (spatial(toa_olr, "mean") / sbc) ** 0.25
    t_eff.rename("toa_effective_temperature")
    return t_eff


def ghe_norm(cubelist):
    """
    Normalised greenhouse effect parameter.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Difference between the region averages.
    """
    t_sfc = spatial(cubelist.extract_strict("surface_temperature"), "mean")
    # t_sfc = spatial(
    #     cubelist.extract_strict("air_temperature").extract(iris.Constraint(level_height=0)),
    #     "mean",
    # )
    t_eff = toa_eff_temp(cubelist)
    one = t_eff.copy(data=np.ones(t_eff.shape))
    one.units = "1"
    gh_norm = one - (t_eff / t_sfc) ** 4
    gh_norm.rename("normalised_greenhouse_effect_parameter")
    return gh_norm