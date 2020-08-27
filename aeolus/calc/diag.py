"""Some commonly used diagnostics in atmospheric science."""
import iris
from iris.exceptions import ConstraintMismatchError as ConMisErr

import numpy as np

from .calculus import d_dz, integrate
from .stats import spatial
from ..const import init_const
from ..coord import coord_to_cube, ensure_bounds, regrid_3d
from ..exceptions import ArgumentError, MissingCubeError
from ..model import um
from ..subset import _dim_constr


__all__ = (
    "air_density",
    "air_temperature",
    "bond_albedo",
    "dry_lapse_rate",
    "flux",
    "geopotential_height",
    "ghe_norm",
    "heat_redist_eff",
    "horiz_wind_cmpnts",
    "precip_sum",
    "sfc_net_energy",
    "sfc_water_balance",
    "toa_cloud_radiative_effect",
    "toa_eff_temp",
    "toa_net_energy",
    "water_path",
)


def _precip_name_mapping(model=um):
    """Generate lists of variable names for `precip_sum()`."""
    return {
        "total": [model.ls_rain, model.ls_snow, model.cv_rain, model.cv_snow],
        "conv": [model.cv_rain, model.cv_snow],
        "stra": [model.ls_rain, model.ls_snow],
        "rain": [model.ls_rain, model.cv_rain],
        "snow": [model.ls_snow, model.cv_snow],
    }


def air_temperature(cubelist, const=None, model=um):
    """
    Get the real temperature from the given cube list.

    If not present, it is attempted to calculate it from other variables,
    Exner pressure or air pressure, and potential temperature.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes containing temperature.
    const: aeolus.const.const.ConstContainer, optional
        Must have `reference_surface_pressure` and `dry_air_gas_constant` as attributes.
        If not given, an attempt is made to retrieve it from cube attributes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of air temperature.
    """
    try:
        return cubelist.extract_strict(model.temp)
    except ConMisErr:
        try:
            thta = cubelist.extract_strict(model.thta)
        except ConMisErr:
            raise MissingCubeError(f"Unable to get air temperature from {cubelist}")

        if len(cubelist.extract(model.exner)) == 1:
            exner = cubelist.extract_strict(model.exner)
        elif len(cubelist.extract(model.pres)) == 1:
            if const is None:
                const = thta.attributes["planet_conf"]
            pres = cubelist.extract(model.pres, strict=True)
            exner = (pres / const.reference_surface_pressure.asc) ** (
                const.dry_air_gas_constant / const.dry_air_spec_heat_press
            ).data
        else:
            raise MissingCubeError(f"Unable to get air temperature from {cubelist}")
        temp = thta * exner
        temp.rename(model.temp)
        temp.convert_units("K")
        return temp


def air_density(cubelist, const=None, model=um):
    """
    Get air density from the given cube list.

    If not present, it is attempted to calculate it from pressure and temperature.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes containing temperature.
    const: aeolus.const.const.ConstContainer, optional
        Must have `dry_air_gas_constant` as an attribute.
        If not given, an attempt is made to retrieve it from cube attributes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of air density.
    """
    try:
        return cubelist.extract_strict(model.dens)
    except ConMisErr:
        try:
            temp = cubelist.extract(model.temp, strict=True)
            pres = cubelist.extract(model.pres, strict=True)
            if const is None:
                const = pres.attributes["planet_conf"]
            rho = pres / (const.dry_air_gas_constant.asc * temp)
            rho.rename(model.dens)
            rho.convert_units("kg m^-3")
            return rho
        except ConMisErr:
            _msg = f"Unable to get variables from\n{cubelist}\nto calculate air density"
            raise MissingCubeError(_msg)


def geopotential_height(cubelist, const=None, model=um):
    """
    Get geopotential height from the given cube list.

    If not present, the altitude coordinate is transformed into a cube.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes containing temperature.
    const: aeolus.const.const.ConstContainer, optional
        Must have `gravity` as an attribute.
        If not given, an attempt is made to retrieve it from cube attributes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of geopotential height.
    """
    try:
        return cubelist.extract_strict(model.ghgt)
    except ConMisErr:
        try:
            cube_w_height = cubelist.extract(_dim_constr(model.z, strict=False))[0]
            if const is None:
                const = cube_w_height.attributes["planet_conf"]
            g_hgt = coord_to_cube(cube_w_height, model.z) * const.gravity.asc
            g_hgt.attributes = {k: v for k, v in cube_w_height.attributes.items() if k != "STASH"}
            ensure_bounds(g_hgt, [model.z])
            g_hgt.rename(model.ghgt)
            g_hgt.convert_units("m^2 s^-2")
            return g_hgt
        except ConMisErr:
            _msg = f"No cubes in \n{cubelist}\nwith {model.z} as a coordinate."
            raise MissingCubeError(_msg)


def flux(cubelist, quantity, axis, weight_by_density=True, model=um):
    r"""
    Calculate horizontal or vertical flux of some quantity.

    .. math::
        F_{x} = u (\rho q),
        F_{y} = v (\rho q),
        F_{z} = w (\rho q)

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    quantity: str or iris.Constraint
        Quantity (present in the cube list).
    axis: str
        Axis of the flux component (x|y|z)
    weight_by_density: bool, optional
        Multiply by a cube of air density (must be present in the input cube list).
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of a flux component with the same dimensions as input cubes.
    """
    if axis.lower() == "x":
        u = cubelist.extract_strict(model.u)
    elif axis.lower() == "y":
        u = cubelist.extract_strict(model.v)
    elif axis.lower() == "z":
        u = cubelist.extract_strict(model.w)
    q = cubelist.extract_strict(quantity)
    fl = u * q
    if weight_by_density:
        fl *= cubelist.extract_strict(model.dens)
    fl.rename(f"flux_of_{quantity}_along_{axis.lower()}_axis")
    return fl


def toa_cloud_radiative_effect(cubelist, kind):
    r"""
    Calculate domain-average TOA cloud radiative effect (CRE).

    .. math::
        CRE_{TOA} = F_{up,clear-sky} - F_{up,all-sky}

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes
    kind: str
        Shortwave ('sw'), longwave ('lw'), or 'total' CRE

    Returns
    -------
    iris.cube.Cube
        Cube of CRE with collapsed spatial dimensions.
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


def toa_net_energy(cubelist, model=um):
    """
    Calculate domain-average TOA energy flux.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of total TOA downward energy flux.
    """
    varnames = [
        model.toa_isr,
        model.toa_osr,
        model.toa_olr,
    ]
    terms = cubelist.extract(varnames)
    if len(terms) != 3:
        raise MissingCubeError(
            f"{varnames} required for TOA energy balance are missing from cubelist:\n{cubelist}"
        )
    terms_ave = []
    for cube in terms:
        terms_ave.append(cube)
    toa_net = terms_ave[0] - terms_ave[1] - terms_ave[2]
    toa_net.rename("toa_net_downward_energy_flux")
    return toa_net


def sfc_net_energy(cubelist, model=um):
    """
    Calculate domain-average surface energy flux.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes with net LW and SW radiation, sensible and latent surface fluxes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of total surface downward energy flux.
    """
    net_down_lw = cubelist.extract_strict(model.sfc_net_down_lw)
    net_down_sw = cubelist.extract_strict(model.sfc_net_down_sw)
    shf = cubelist.extract_strict(model.shf)
    lhf = cubelist.extract_strict(model.shf)
    sfc_net = net_down_lw + net_down_sw - shf - lhf
    sfc_net.rename("surface_net_downward_energy_flux")
    return sfc_net


def sfc_water_balance(cubelist, const=None, model=um):
    """
    Calculate domain-average precipitation minus evaporation.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    const: aeolus.const.const.ConstContainer, optional
        Must have a `ScalarCube` of `condensible_density` as an attribute.
        If not given, attempt is made to retrieve it from cube attributes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of total surface downward water flux (P-E).
    """
    if const is None:
        const = cubelist[0].attributes["planet_conf"]
    try:
        evap = cubelist.extract_strict(model.sfc_evap)
    except ConMisErr:
        try:
            lhf = cubelist.extract_strict(model.sfc_lhf)
            evap = lhf / const.condensible_heat_vaporization.asc
            evap /= const.condensible_density.asc
        except (KeyError, ConMisErr):
            raise MissingCubeError(f"Cannot retrieve evaporation from\n{cubelist}")
    try:
        precip = cubelist.extract_strict(model.ppn)
        precip /= const.condensible_density.asc
    except ConMisErr:
        precip = precip_sum(cubelist, ptype="total", const=const, model=model)
    precip.convert_units("mm h^-1")
    evap.convert_units("mm h^-1")
    net = precip - evap
    net.rename("surface_net_downward_water_flux")  # FIXME
    return net


def precip_sum(cubelist, ptype="total", const=None, model=um):
    """
    Calculate a sum of different types of precipitation [:math:`mm~day^{-1}`].

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    ptype: str, optional
        Precipitation type (total|stra|conv|rain|snow).
    const: aeolus.const.const.ConstContainer, optional
        Must have a `ScalarCube` of `condensible_density` as an attribute.
        If not given, attempt to retrieve it from cube attributes.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Sum of cubes of precipitation with units converted to mm per day.
    """
    try:
        varnames = _precip_name_mapping(model=model)[ptype]
    except KeyError:
        raise ArgumentError(f"Unknown ptype={ptype}")
    if len(cubelist.extract(varnames)) == 0:
        raise MissingCubeError(
            f"{varnames} required for ptype={ptype} are missing from cubelist:\n{cubelist}"
        )
    precip = 0.0
    for varname in varnames:
        try:
            cube = cubelist.extract_strict(varname)
            if const is None:
                const = cube.attributes.get("planet_conf", None)
            precip += cube
        except ConMisErr:
            pass
    if const is not None:
        precip /= const.condensible_density.asc
        precip.convert_units("mm day^-1")
    precip.rename(f"{ptype}_precip_rate")
    return precip


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
        Cube of eta parameter with collapsed spatial dimensions.
    """
    toa_olr = cubelist.extract_strict("toa_outgoing_longwave_flux")
    toa_olr_a = spatial(toa_olr.extract(region_a.constraint), "mean")
    toa_olr_b = spatial(toa_olr.extract(region_b.constraint), "mean")
    eta = toa_olr_a / toa_olr_b
    eta.rename("heat_redistribution_efficiency")
    return eta


def toa_eff_temp(cubelist):
    r"""
    Calculate effective temperature from TOA OLR.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Cube of :math:`T_{eff}` with collapsed spatial dimensions.
    """
    toa_olr = cubelist.extract_strict("toa_outgoing_longwave_flux")
    sbc = init_const().stefan_boltzmann
    try:
        t_eff = (spatial(toa_olr, "mean") / sbc) ** 0.25
    except ValueError:
        t_eff = (spatial(toa_olr, "mean") / sbc.asc) ** 0.25
    t_eff.rename("toa_effective_temperature")
    return t_eff


def ghe_norm(cubelist):
    r"""
    Normalised greenhouse effect parameter.

    .. math::
        GHE = 1 - \left(\frac{T_{eff}}{T_{sfc}}\right)^{1/4}

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.

    Returns
    -------
    iris.cube.Cube
        Cube of greenhouse effect parameter with collapsed spatial dimensions.
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


def bond_albedo(cubelist, const=None):
    r"""
    Bold albedo.

    .. math::
        4 \frac{OSR_{TOA}}{S_{0}}

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes.
    const: aeolus.const.const.ConstContainer, optional
        Must have a `ScalarCube` of `condensible_density` as an attribute.
        If not given, attempt to retrieve it from cube attributes.

    Returns
    -------
    iris.cube.Cube
        Cube of bond albedo with collapsed spatial dimensions.
    """
    toa_osr = spatial(cubelist.extract_strict("toa_outgoing_shortwave_flux"), "mean")
    if const is None:
        const = toa_osr.attributes["planet_conf"]
    sc = const.solar_constant
    try:
        b_alb = 4 * toa_osr / sc
    except ValueError:
        b_alb = 4 * toa_osr / sc.asc
    b_alb.rename("bond_albedo")
    return b_alb


def water_path(cubelist, kind="water_vapour", model=um):
    r"""
    Water vapour or condensate path, i.e. a vertical integral of a water phase.

    .. math::
        WP = \int_{z_{sfc}}^{z_{top}} \rho q dz

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes containing appropriate mixing ratio and air density.
    kind: str, optional
        Short name of the water phase to be integrated.
        Options are water_vapour (default) | liquid_water | ice_water | cloud_water
        `cloud_water` is the sum of liquid and ice phases.
    model: aeolus.model.Model, optional
        Model class with relevant coordinate names.
        `model.z` is used as a vertical coordinate for integration.

    Returns
    -------
    iris.cube.Cube
        Cube of water path with collapsed vertical dimension.
    """
    if kind == "water_vapour":
        q = cubelist.extract_strict("specific_humidity")
    elif kind == "liquid_water":
        q = cubelist.extract_strict("mass_fraction_of_cloud_liquid_water_in_air")
    elif kind == "ice_water":
        q = cubelist.extract_strict("mass_fraction_of_cloud_ice_in_air")
    elif kind == "cloud_water":
        q = cubelist.extract_strict("mass_fraction_of_cloud_liquid_water_in_air")
        q += cubelist.extract_strict("mass_fraction_of_cloud_ice_in_air")
    rho = cubelist.extract_strict("air_density")
    wp = integrate(q * rho, model.z)
    wp.rename(f"{kind}_path")
    return wp


def dry_lapse_rate(cubelist, model=um):
    r"""
    Dry lapse rate, or the change of air temperature with altitude.

    .. math::
        \gamma = \partial T_{air} / \partial z

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        Input list of cubes containing temperature.
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    iris.cube.Cube
        Cube of dT/dz.
    """
    temp = cubelist.extract_strict(model.temp)
    return d_dz(temp, model=model)


def horiz_wind_cmpnts(cubelist, model=um):
    """
    Extract u and v wind components from a cube list and interpolate v on u's grid if necessary.

    Parameters
    ----------
    cubelist: iris.cube.CubeList
        List of cubes with horizontal wind components
    model: aeolus.model.Model, optional
        Model class with relevant variable names.

    Returns
    -------
    u, v: iris.cube.Cube
        Cubes of wind components.
    """
    # use relaxed extracting
    u = cubelist.extract(model.u)[0]
    v = cubelist.extract(model.v)[0]
    # interpolate v on u's grid if coordinates are different
    v = regrid_3d(v, u, model=model)
    return u, v
