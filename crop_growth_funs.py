#!/usr/bin/env python
# -*- coding: utf-8 -*-

# AquaCrop crop growth model

import os
import shutil
import sys
import math
import gc
import numpy as np

def canopy_cover_development(CC0, CCx, CGC, CDC, dt, Mode):
    """Function to calculate canopy cover development by end of the 
    current simulation day
    """
    dims = CC0.shape
    nr, nlat, nlon = dims[0], dims[1], dims[2]
    arr_zeros = np.zeros((nr, nlat, nlon))
    if Mode == 'Growth':
        CC = (CC0 * np.exp(CGC * dt))
        cond1 = (CC > (CCx / 2.))
        CC[cond1] = (CCx - 0.25 * np.divide(CCx, CC0, out=np.copy(arr_zeros), where=CC0!=0) * CCx * np.exp(-CGC * dt))[cond1]
        CC = np.clip(CC, None, CCx)
    elif Mode == 'Decline':
        CC = np.zeros((CC0.shape))
        cond2 = (CCx >= 0.001)
        CC[cond2] = (CCx * (1. - 0.05 * (np.exp(dt * np.divide(CDC, CCx, out=np.copy(arr_zeros), where=CCx!=0)) - 1.)))[cond2]

    CC = np.clip(CC, 0, 1)
    return CC

def canopy_cover_required_time(CCprev, CC0, CCx, CGC, CDC, dt, tSum, Mode):
    """Function to find required time to reach CC at end of previous 
    day, given current CGC or CDC
    """
    dims = CCprev.shape
    nr, nlat, nlon = dims[0], dims[1], dims[2]
    
    arr_zeros = np.zeros((nr, nlat, nlon))
    if Mode == 'CGC':
        CGCx = np.copy(arr_zeros)
        cond1 = (CCprev <= (CCx / 2))
        x = np.divide(CCprev, CC0, out=np.copy(arr_zeros), where=CC0!=0)
        CGCx_divd = np.log(x, out=np.copy(arr_zeros), where=x>0)
        CGCx_divs = tSum - dt
        CGCx[cond1] = np.divide(CGCx_divd, CGCx_divs, out=np.copy(arr_zeros), where=CGCx_divs!=0)[cond1]
        cond2 = np.logical_not(cond1)

        x1 = np.divide(0.25 * CCx * CCx, CC0, out=np.copy(arr_zeros), where=CC0!=0)
        x2 = CCx - CCprev
        x3 = np.divide(x1, x2, out=np.copy(arr_zeros), where=x2!=0)
        CGCx_divd = np.log(x3, out=np.copy(arr_zeros), where=x3>0)
        CGCx_divs = tSum - dt
        CGCx[cond2] = np.divide(CGCx_divd, CGCx_divs, out=np.copy(arr_zeros), where=CGCx_divs!=0)[cond2]
        tReq = (tSum - dt) * np.divide(CGCx, CGC, out=np.copy(arr_zeros), where=CGC!=0)
    elif Mode == 'CDC':
        x1 = np.divide(CCprev, CCx, out=np.copy(arr_zeros), where=CCx!=0)
        x2 = 1 + (1 - np.divide(CCprev, CCx, out=np.copy(arr_zeros), where=CCx!=0)) / 0.05
        tReq_divd = np.log(x2, out=np.copy(arr_zeros), where=x2!=0)
        tReq_divs = np.divide(CDC, CCx, out=np.copy(arr_zeros), where=CCx!=0)
        tReq = np.divide(tReq_divd, tReq_divs, out=np.copy(arr_zeros), where=tReq_divs!=0)
    return tReq

def adjust_CCx(CCprev, CC0, CCx, CGC, CDC, dt, tSum, CanopyDevEnd):
    """Function to adjust CCx value for changes in CGC due to water 
    stress during the growing season
    """
    # Get time required to reach CC on previous day, then calculate
    # adjusted CCx
    tCCtmp = canopy_cover_required_time(CCprev, CC0, CCx, CGC, CDC, dt, tSum, 'CGC')
    cond1 = (tCCtmp > 0)
    tCCtmp[cond1] += ((CanopyDevEnd - tSum) + dt)[cond1]
    CCxAdj = canopy_cover_development(CC0, CCx, CGC, CDC, tCCtmp, 'Growth')
    CCxAdj[np.logical_not(cond1)] = 0
    return CCxAdj

def update_CCx_and_CDC(CCprev, CDC, CCx, dt):
    """Function to update CCx and CDC parameter values for 
    rewatering in late season of an early declining canopy
    """
    CCxAdj = CCprev / (1 - 0.05 * (np.exp(dt * (np.divide(CDC, CCx, out=np.zeros_like(CCx), where=CCx!=0))) - 1))
    CDCadj = CDC * np.divide(CCxAdj, CCx, out=np.zeros_like(CCx), where=CCx!=0)
    return CCxAdj,CDCadj

def update_CC_after_senescence(growing_season, CC, CCprev, CC0, CC0adj, CGC, CDC, CCx, CCxAct, CCxW, CCxEarlySen, Ksw_Sen, tEarlySen, tCCadj, dtCC, Emergence, Senescence, PrematSenes, CropDead):

    dims = CC.shape
    nr, nlat, nlon = dims[0], dims[1], dims[2]
    CCsen = np.zeros((nr, nlat, nlon))

    cond7 = (growing_season & (tCCadj >= Emergence))

    # Check for early canopy senescence starting/continuing due to severe
    # water stress
    cond71 = (cond7 & ((tCCadj < Senescence) | (tEarlySen > 0)))

    # Early canopy senescence
    cond711 = (cond71 & (Ksw_Sen < 1))
    
    CDCadj = np.zeros_like(CDC)
    cond7112 = (cond711 & (Ksw_Sen > 0.99999))
    CDCadj[cond7112] = 0.0001
    cond7113 = (cond711 & np.logical_not(cond7112))
    CDCadj[cond7113] = ((1 - (Ksw_Sen ** 8)) * CDC)[cond7113]

    # Get new canopy cover size after senescence
    cond7114 = (cond711 & (CCxEarlySen < 0.001))
    CCsen[cond7114] = 0

    # Get time required to reach CC at end of previous day, given CDCadj
    cond7115 = (cond711 & np.logical_not(cond7114))
    tReq = canopy_cover_required_time(CCprev, CC0adj, CCxEarlySen, CGC, CDCadj, dtCC, tCCadj, 'CDC')

    # Calculate GDD's for canopy decline and determine new canopy size
    tmp_tCC = tReq + dtCC
    tmp_CCsen = canopy_cover_development(CC0adj, CCxEarlySen, CGC, CDCadj, tmp_tCC, 'Decline')
    CCsen[cond7115] = tmp_CCsen[cond7115]

    # Update canopy cover size
    cond7116 = (cond711 & (tCCadj < Senescence))

    # Limit CC to CCx
    CCsen[cond7116] = np.clip(CCsen, None, CCx)[cond7116]

    # CC cannot be greater than value on previous day
    CC[cond7116] = CCsen[cond7116]
    CC[cond7116] = np.clip(CC, None, CCprev)[cond7116]

    # Update maximum canopy cover size during growing season
    CCxAct[cond7116] = CC[cond7116]

    # Update CC0 if current CC is less than initial canopy cover size at
    # planting
    cond71161 = (cond7116 & (CC < CC0))
    CC0adj[cond71161] = CC[cond71161]
    cond71162 = (cond7116 & np.logical_not(cond71161))
    CC0adj[cond71162] = CC0[cond71162]

    # Update CC to account for canopy cover senescence due to water stress
    cond7117 = (cond711 & np.logical_not(cond7116))
    CC[cond7117] = np.clip(CC, None, CCsen)[cond7117]

    # Check for crop growth termination
    cond7118 = (cond711 & ((CC < 0.001) & np.logical_not(CropDead)))
    CC[cond7118] = 0
    CropDead[cond7118] = True

    # Otherwise there is no water stress
    cond712 = (cond71 & np.logical_not(cond711))
    PrematSenes[cond712] = False

    # Rewatering of canopy in late season: get adjusted values of CCx and
    # CDC and update CC
    cond7121 = (cond712 & ((tCCadj > Senescence) & (tEarlySen > 0)))
    tmp_tCC = tCCadj - dtCC - Senescence
    CCxAdj,CDCadj = update_CCx_and_CDC(CCprev, CDC, CCx, tmp_tCC)
    # tmp_CCxAdj,tmp_CDCadj = update_CCx_and_CDC(CCprev, CDC, CCx, tmp_tCC)
    # CCxAdj[cond7121] = tmp_CCxAdj[cond7121]
    # CDCadj[cond7121] = tmp_CDCadj[cond7121]
    tmp_tCC = tCCadj - Senescence
    tmp_CC = canopy_cover_development(CC0adj, CCxAdj, CGC, CDCadj, tmp_tCC, 'Decline')
    CC[cond7121] = tmp_CC[cond7121]

    # Check for crop growth termination
    cond71211 = (cond7121 & ((CC < 0.001) & np.logical_not(CropDead)))
    CC[cond71211] = 0
    CropDead[cond71211] = True

    # Reset early senescence counter
    tEarlySen[cond712] = 0

    # Adjust CCx for effects of withered canopy
    CCxW[cond71] = np.clip(CCxW, CC, None)[cond71]
    # return CC, CC0adj, CCxAct, CCxW, CropDead, PrematSenes, tEarlySen
    
def actual_canopy_development(growing_season, Emergence, Maturity, Senescence, tCC, tCCadj, dtCC, CanopyDevEnd, CC0, CC0adj, CGC, CCx, CDC, Ksw_Exp, CC, CCprev, CCxAct):

    # CCprev = np.copy(CC)
    
    # No canopy development before emergence/germination or after maturity
    cond4 = (growing_season & ((tCCadj < Emergence) | (np.round(tCCadj) > Maturity)))
    CC[cond4] = 0

    # Otherwise, canopy growth can occur
    cond5 = (growing_season & np.logical_not(cond4) & (tCCadj < CanopyDevEnd))
    cond51 = (cond5 & (CCprev <= CC0adj))

    # Very small initial CC as it is first day or due to senescence. In
    # this case, assume no leaf expansion stress
    CC[cond51] = (CC0adj * np.exp(CGC * dtCC))[cond51]

    # Canopy growing
    cond52 = (cond5 & np.logical_not(cond51))

    # Canopy approaching maximum size
    cond521 = (cond52 & (CCprev >= (0.9799 * CCx)))
    tmp_tCC = tCC - Emergence
    tmp_CC = canopy_cover_development(CC0, CCx, CGC, CDC, tmp_tCC, 'Growth')
    CC[cond521] = tmp_CC[cond521]
    CC0adj[cond521] = CC0[cond521]

    # Adjust canopy growth coefficient for leaf expansion water stress
    # effects
    cond522 = (cond52 & np.logical_not(cond521))
    CGCadj = CGC * Ksw_Exp

    # Adjust CCx for change in CGC
    cond5221 = (cond522 & (CGCadj > 0))
    # tmp_CCxAdj = self.adjust_CCx(self.CCprev, self.CC0adj, self.CCx, CGCadj, self.CDC, dtCC, tCCadj)
    # CCxAdj[cond5221] = tmp_CCxAdj[cond5221]
    CCxAdj = adjust_CCx(CCprev, CC0adj, CCx, CGCadj, CDC, dtCC, tCCadj, CanopyDevEnd)

    cond52211 = (cond5221 & (CCxAdj > 0))

    # Approaching maximum canopy size
    cond522111 = (cond52211 & (np.abs(CCprev - CCx) < 0.00001))
    tmp_tCC = tCC - Emergence
    tmp_CC = canopy_cover_development(CC0, CCx, CGC, CDC, tmp_tCC, 'Growth')
    CC[cond522111] = tmp_CC[cond522111]

    # Determine time required to reach CC on previous day, given CGCadj
    # value
    cond522112 = (cond52211 & np.logical_not(cond522111))
    tReq = canopy_cover_required_time(CCprev, CC0adj, CCxAdj, CGCadj, CDC, dtCC, tCCadj, 'CGC')
    tmp_tCC = tReq + dtCC

    # Determine new canopy size
    cond5221121 = (cond522112 & (tmp_tCC > 0))
    tmp_CC = canopy_cover_development(CC0adj, CCxAdj, CGCadj, CDC, tmp_tCC, 'Growth')
    CC[cond5221121] = tmp_CC[cond5221121]

    # No canopy growth (line 110)
    cond5221122 = (cond522112 & np.logical_not(cond5221121))
    CC[cond5221122] = CCprev[cond5221122]

    # No canopy growth (line 115)
    cond52212 = (cond5221 & np.logical_not(cond52211))
    CC[cond52212] = CCprev[cond52212]

    # No canopy growth (line 119)
    cond5222 = (cond522 & np.logical_not(cond5221))
    CC[cond5222] = CCprev[cond5222]

    # Update CC0 if current canopy cover if less than initial canopy cover size at planting
    cond52221 = (cond5222 & (CC < CC0adj))
    CC0adj[cond52221] = CC[cond52221]

    # Update actual maximum canopy cover size during growing season
    cond53 = (cond5 & (CC > CCxAct))
    CCxAct[cond53] = CC[cond53]

    # No more canopy growth is possible or canopy is in decline (line 132)
    cond6 = (growing_season & np.logical_not(cond4 | cond5) & (tCCadj > CanopyDevEnd))

    # Mid-season stage - no canopy growth: update actual maximum canopy
    # cover size during growing season only (i.e. do not update CC)
    cond61 = (cond6 & (tCCadj < Senescence))
    CC[cond61] = CCprev[cond61]
    cond611 = (cond61 & (CC > CCxAct))
    CCxAct[cond611] = CC[cond611]

    # Late season stage - canopy decline: update canopy decline coefficient
    # for difference between actual and potential CCx, and determine new
    # canopy size
    cond62 = (cond6 & np.logical_not(cond61))
    CDCadj = (CDC * np.divide(CCxAct, CCx, out=np.zeros_like(CCx), where=CCx!=0))
    # CDCadj[cond62] = (self.CDC * np.divide(self.CCxAct, self.CCx, out=np.zeros_like(self.CCx), where=self.CCx!=0))[cond62]
    tmp_tCC = tCCadj - Senescence
    tmp_CC = canopy_cover_development(CC0adj, CCxAct, CGC, CDCadj, tmp_tCC, 'Decline')
    CC[cond62] = tmp_CC[cond62]
    return CC, CC0adj, CCxAct
    
def potential_canopy_development(growing_season, Emergence, Maturity, Senescence, tCC, dtCC, CanopyDevEnd, CC0, CGC, CCx, CDC, CC_NS, CCxAct_NS, CCxW_NS):

    CC_NSprev = np.copy(CC_NS)

    # No canopy development before emergence/germination or after maturity
    cond1 = (growing_season & ((tCC < Emergence) | (np.round(tCC) > Maturity)))
    CC_NS[cond1] = 0

    # Canopy growth can occur
    cond2 = (growing_season & np.logical_not(cond1) & (tCC < CanopyDevEnd))

    # Very small initial CC as it is first day or due to senescence. In this
    # case assume no leaf expansion stress
    cond21 = (cond2 & (CC_NSprev <= CC0))
    CC_NS[cond21] = (CC0 * np.exp(CGC * dtCC))[cond21]

    # Canopy growing
    cond22 = (cond2 & np.logical_not(cond21))
    tmp_tCC = tCC - Emergence
    tmp_CC_NS = canopy_cover_development(CC0, CCx, CGC, CDC, tmp_tCC, 'Growth')
    CC_NS[cond22] = tmp_CC_NS[cond22]

    # Update maximum canopy cover size in growing season
    CCxAct_NS[cond2] = CC_NS[cond2]

    # No more canopy growth is possible or canopy in decline
    cond3 = (growing_season & np.logical_not(cond1 | cond2) & (tCC > CanopyDevEnd))
    # Set CCx for calculation of withered canopy effects
    CCxW_NS[cond3] = CCxAct_NS[cond3]

    # Mid-season stage - no canopy growth, so do not update CC_NS
    cond31 = (cond3 & (tCC < Senescence))
    CC_NS[cond31] = CC_NSprev[cond31]
    CCxAct_NS[cond31] = CC_NS[cond31]

    # Late-season stage - canopy decline
    cond32 = (cond3 & np.logical_not(cond31))
    tmp_tCC = tCC - Emergence
    tmp_CC_NS = canopy_cover_development(CC0, CCx, CGC, CDC, tmp_tCC, 'Decline')
    CC_NS[cond32] = tmp_CC_NS[cond32]
    return CC_NS, CCxAct_NS, CCxW_NS
    
def water_stress(p_lo, p_up, fshape_w, et0, ETadj, tEarlySen, adjust_senescence_threshold, beta, TAW, Dr):

    dims = et0.shape
    nr, nlat, nlon = dims[0], dims[1], dims[2]
    
    # Adjust stress thresholds for Et0 on current day (don't do this for
    # pollination water stress coefficient)
    cond1 = (ETadj == 1)
    for stress in range(3):
        p_up[stress,:][cond1] = (p_up[stress,:] + (0.04 * (5 - et0)) * (np.log10(10 - 9 * p_up[stress,:])))[cond1]
        p_lo[stress,:][cond1] = (p_lo[stress,:] + (0.04 * (5 - et0)) * (np.log10(10 - 9 * p_lo[stress,:])))[cond1]

    # Adjust senescence threshold if early senescence triggered
    if adjust_senescence_threshold:
        cond2 = (tEarlySen > 0)
        p_up[2,:][cond2] = (p_up[2,:] * (1. - (beta / 100)))[cond2]

    # Limit adjusted values
    p_up = np.clip(p_up, 0, 1)
    p_lo = np.clip(p_lo, 0, 1)

    # Calculate relative depletion
    Drel = np.zeros((4, nr, nlat, nlon))
    # No water stress
    cond1 = (Dr <= (p_up * TAW))
    Drel[cond1] = 0

    # Partial water stress
    cond2 = (Dr >  (p_up * TAW)) & (Dr < (p_lo * TAW)) & np.logical_not(cond1)
    x1 = p_lo - np.divide(Dr, TAW, out=np.zeros_like(Drel), where=TAW!=0)
    x2 = p_lo - p_up
    Drel[cond2] = (1 - np.divide(x1, x2, out=np.zeros_like(Drel), where=x2!=0))[cond2]

    # Full water stress
    cond3 = (Dr >= (p_lo * TAW)) & np.logical_not(cond1 | cond2)
    Drel[cond3] = 1         

    # Calculate root zone stress coefficients
    idx = np.arange(0,3)
    x1 = np.exp(Drel[idx,:] * fshape_w[idx,:]) - 1
    x2 = np.exp(fshape_w[idx,:]) - 1
    Ks = (1 - np.divide(x1, x2, out=np.zeros_like(x2), where=x2!=0))

    # Water stress coefficients (leaf expansion, stomatal closure,
    # senescence, pollination failure)
    Ksw_Exp = np.copy(Ks[0,:])
    Ksw_Sto = np.copy(Ks[1,:])
    Ksw_Sen = np.copy(Ks[2,:])
    Ksw_Pol = 1 - Drel[3,:]

    # Mean water stress coefficient for stomatal closure
    Ksw_StoLin = 1 - Drel[1,:]
    return Ksw_Exp, Ksw_Sto, Ksw_Sen, Ksw_Pol, Ksw_StoLin

def root_development(growing_season, calendar_type, DAP, DelayedCDs, DelayedGDDs, GDD, GDDcum, Zmin, Zmax, PctZmin, Emergence, MaxRooting, fshape_r, fshape_ex, TrRatio, Germination):

    dims = growing_season.shape
    nr, nlat, nlon = dims[0], dims[1], dims[2]
    
    # Adjust time for any delayed development
    if calendar_type == 1:
        tAdj = (DAP - DelayedCDs)
    elif calendar_type == 2:
        tAdj = (GDDcum - DelayedGDDs)

    # Calculate root expansion
    Zini = Zmin * (PctZmin / 100)
    t0 = np.round(Emergence / 2)
    tmax = MaxRooting
    if calendar_type == 1:
        tOld = (tAdj - 1)
    elif calendar_type == 2:
        tOld = (tAdj - GDD)

    tAdj[np.logical_not(growing_season)] = 0
    tOld[np.logical_not(growing_season)] = 0

    # Potential root depth on previous day
    # ####################################

    ZrOld = np.zeros((nr, nlat, nlon))
    cond2 = (growing_season & (tOld >= tmax))
    ZrOld[cond2] = Zmax[cond2]
    cond3 = (growing_season & np.logical_not(cond2) & (tOld <= t0))
    ZrOld[cond3] = Zini[cond3]
    cond4 = (growing_season & (np.logical_not(cond2 | cond3)))
    X_divd = tOld - t0
    X_divs = tmax - t0
    X = np.divide(X_divd, X_divs, out=np.zeros_like(t0), where=X_divs!=0)
    ZrOld_exp = np.divide(1, fshape_r, out=np.zeros_like(fshape_r), where=cond4)
    ZrOld_pow = np.power(X, ZrOld_exp, out=np.zeros_like(ZrOld), where=cond4)
    ZrOld[cond4] = (Zini + (Zmax - Zini) * ZrOld_pow)[cond4]        
    cond5 = (growing_season & (ZrOld < Zmin))
    ZrOld[cond5] = Zmin[cond5]

    # Potential root depth on current day
    # ###################################

    # TODO: write function potential_root_depth(growing_season, tAdj, tmax, Zmin, Zmax, t0, fshape_r):
    Zr = np.zeros((nr, nlat, nlon))
    cond6 = (growing_season & (tAdj >= tmax))
    Zr[cond6] = Zmax[cond6]
    cond7 = (growing_season & np.logical_not(cond6) & (tAdj <= t0))
    Zr[cond7] = Zini[cond7]
    cond8 = (growing_season & (np.logical_not(cond6 | cond7)))
    X_divd = tAdj - t0
    X_divs = tmax - t0
    X = np.divide(X_divd, X_divs, out=np.zeros_like(t0), where=X_divs!=0)
    Zr_exp = np.divide(1, fshape_r, out=np.zeros_like(fshape_r), where=cond8)
    Zr_pow = np.power(X, Zr_exp, out=np.zeros_like(Zr), where=cond8)
    Zr[cond8] = (Zini + (Zmax - Zini) * Zr_pow)[cond8]
    cond9 = (growing_season & (Zr < Zmin))
    Zr[cond9] = Zmin[cond9]

    # Determine rate of change, adjust for any stomatal water stress
    # ##############################################################

    dZr = Zr - ZrOld
    cond10 = (growing_season & (TrRatio < 0.9999))
    cond101 = (cond10 & (fshape_ex >= 0))        
    dZr[cond101] = (dZr * TrRatio)[cond101]
    cond102 = (cond10 & np.logical_not(cond101))
    fAdj_divd = (np.exp(TrRatio * fshape_ex) - 1)
    fAdj_divs = (np.exp(fshape_ex) - 1)
    fAdj = np.divide(fAdj_divd, fAdj_divs, out=np.zeros_like(Zr), where=fAdj_divs!=0)
    dZr[cond102] = (dZr * fAdj)[cond102]

    # Adjust root expansion for failure to germinate (roots cannot expand
    # if crop has not germinated)
    dZr[np.logical_not(Germination)] = 0
    return dZr, Zr

def water_content_affecting_germination(th, th_fc, th_wp, dz, dzsum, zGerm):

    dims = th_fc.shape
    nc, nr, nlat, nlon = dims[0], dims[1], dims[2], dims[3]
    
    zgerm = np.copy(zGerm)

    # Here we force zGerm to have a maximum value equal to the depth of the
    # deepest soil compartment
    zgerm[zgerm > np.sum(dz, axis=0)] = np.sum(dz, axis=0)

    # Add rotation, lat, lon dimensions to dz and dzsum
    dz = dz[:,None,None,None] * np.ones((nr, nlat, nlon))
    dzsum = dzsum[:,None,None,None] * np.ones((nr, nlat, nlon))
    
    # Find compartments covered by top soil layer affecting germination
    comp_sto = (np.round(dzsum * 1000) <= np.round(zgerm * 1000))  # round to nearest mm

    # Calculate water content in top soil layer
    arr_zeros = np.zeros((nc, nr, nlat, nlon))
    Wr_comp   = np.copy(arr_zeros)
    WrFC_comp = np.copy(arr_zeros)
    WrWP_comp = np.copy(arr_zeros)

    # Determine fraction of compartment covered by top soil layer
    factor = 1. - np.round(((dzsum - zgerm) / dz), 3)
    # factor = np.clip(factor, 0, 1) * growing_season * comp_sto
    factor = np.clip(factor, 0, 1) * comp_sto

    # Increment water storages (mm)
    Wr_comp = np.round((factor * 1000 * th * dz))
    Wr_comp = np.clip(Wr_comp, 0, None)
    Wr = np.sum(Wr_comp, axis=0)

    WrFC_comp = np.round((factor * 1000 * th_fc * dz))
    WrFC = np.sum(WrFC_comp, axis=0)

    WrWP_comp = np.round((factor * 1000 * th_wp * dz))
    WrWP = np.sum(WrWP_comp, axis=0)

    # Calculate proportional water content
    WrTAW = WrFC - WrWP
    WcProp = 1 - np.divide((WrFC - Wr), WrTAW, out=np.zeros_like(WrTAW), where=WrTAW!=0)
    return WcProp

def growing_degree_day(Tmax, Tmin, Tbase, Tupp, method):

    if method == 1:
        Tmean = ((Tmax + Tmin) / 2)
        Tmean = np.clip(Tmean, Tbase, Tupp)
    elif method == 2:
        Tmax = np.clip(Tmax, Tbase, Tupp)
        Tmin = np.clip(Tmin, Tbase, Tupp)
        Tmean = ((Tmax + Tmin) / 2)
    elif method == 3:
        Tmax = np.clip(Tmax, Tbase, Tupp)
        Tmin = np.clip(Tmin, None, Tupp)
        Tmean = np.clip(Tmean, Tbase, None)
    GDD = (Tmean - Tbase)
    return GDD
