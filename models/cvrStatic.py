''' Calculate CVR impacts using a targetted set of static loadflows. '''

import json, os, sys, tempfile, webbrowser, time, shutil, datetime, subprocess
import math, re, datetime as dt
import multiprocessing
from os.path import join as pJoin
from jinja2 import Template
from matplotlib import pyplot as plt
import __util__ as util

# Locational variables so we don't have to rely on OMF being in the system path.
_myDir = os.path.dirname(os.path.abspath(__file__))
_omfDir = os.path.dirname(_myDir)

# OMF imports
sys.path.append(_omfDir)
import feeder
from solvers import gridlabd

# Our HTML template for the interface:
with open(pJoin(_myDir,"cvrStatic.html"),"r") as tempFile:
	template = Template(tempFile.read())

def renderTemplate(modelDir="", absolutePaths=False, datastoreNames={}):
	''' Render the model template to an HTML string.
	By default render a blank one for new input.
	If modelDir is valid, render results post-model-run.
	If absolutePaths, the HTML can be opened without a server. '''
	try:
		allInputData = open(pJoin(modelDir,"allInputData.json")).read()
	except IOError:
		allInputData = None
	try:
		allOutputData = open(pJoin(modelDir,"allOutputData.json")).read()
	except IOError:
		allOutputData = None
	if absolutePaths:
		# Parent of current folder.
		pathPrefix = _omfDir
	else:
		pathPrefix = ""
	return template.render(allInputData=allInputData,
		allOutputData=allOutputData, pathPrefix=pathPrefix,
		datastoreNames=datastoreNames)

def renderAndShow(modelDir="", datastoreNames={}):
	''' Render and open a template (blank or with output) in a local browser. '''
	with tempfile.NamedTemporaryFile() as temp:
		temp.write(renderTemplate(modelDir=modelDir, absolutePaths=True))
		temp.flush()
		os.rename(temp.name, temp.name + ".html")
		fullArg = "file://" + temp.name + ".html"
		webbrowser.open(fullArg)
		# It's going to SPACE! Could you give it a SECOND to get back from SPACE?!
		time.sleep(1)

def create(parentDirectory, inData):
	''' Make a directory for the model to live in, and put the input data into it. '''
	modelDir = pJoin(parentDirectory,inData["user"],inData["modelName"])
	os.mkdir(modelDir)
	inData["created"] = str(datetime.datetime.now())
	with open(pJoin(modelDir,"allInputData.json"),"w") as inputFile:
		json.dump(inData, inputFile, indent=4)
	# TODO: copy datastore data we need.

def _roundOne(x,direc):
	''' Round x in direc (up/down) to 1 sig fig. '''
	thou = 10.0**math.floor(math.log10(x))
	decForm = x/thou
	if direc=='up':
		return math.ceil(decForm)*thou
	elif direc=='down':
		return math.floor(decForm)*thou
	else:
		raise Exception

def run(modelDir):
	''' Run the model in its directory. '''
	# TODO: implement.
	pass

def runForeground(modelDir):
	''' Run the model in the foreground. WARNING: can take about a minute. '''
	# TODO: implment.
	pass

def cancel(modelDir):
	''' PV Watts runs so fast it's pointless to cancel a run. '''
	# TODO: implement.
	pass

def _runAnalysis(tree, monthData, rates):
	''' Run CVR analysis. '''
	# Graph the SCADA data.
	fig = plt.figure(figsize=(17,5))
	indices = [r['monthName'] for r in monthData]
	d1 = [r['histPeak']/(10**3) for r in monthData]
	d2 = [r['histAverage']/(10**3) for r in monthData]
	ticks = range(len(d1))
	plt.bar(ticks,d1,color='gray')
	plt.bar(ticks,d2,color='dimgray')
	plt.xticks([t+0.5 for t in ticks],indices)
	plt.ylabel('Mean and peak historical power consumptions (kW)')
	# Graph feeder.
	myGraph = feeder.treeToNxGraph(tree)
	feeder.latLonNxGraph(myGraph, neatoLayout=False)
	# Get the load levels we need to test.
	allLoadLevels = [x.get('histPeak',0) for x in monthData] + [y.get('histAverage',0) for y in monthData]
	maxLev = _roundOne(max(allLoadLevels),'up')
	minLev = _roundOne(min(allLoadLevels),'down')
	tenLoadLevels = range(int(minLev),int(maxLev),int((maxLev-minLev)/10))
	# Gather variables from the feeder.
	for key in tree.keys():
		# Set clock to single timestep.
		if tree[key].get('clock','') == 'clock':
			tree[key] = {"timezone":"PST+8PDT",
				"stoptime":"'2013-01-01 00:00:00'",
				"starttime":"'2013-01-01 00:00:00'",
				"clock":"clock"}
		# Remove all includes.
		if tree[key].get('omftype','') == '#include':
			del key
		# Save swing node index.
		if tree[key].get('bustype','').lower() == 'swing':
			swingIndex = key
			swingName = tree[key].get('name')
	# Find the substation regulator and config.
	for key in tree:
		if tree[key].get('object','') == 'regulator' and tree[key].get('from','') == swingName:
			regIndex = key
			regConfName = tree[key]['configuration']
	for key in tree:
		if tree[key].get('name','') == regConfName:
			regConfIndex = key
	# Set substation regulator to manual operation.
	baselineTap = 3 # GLOBAL VARIABLE FOR DEFAULT TAP POSITION
	tree[regConfIndex] = {
		'name':tree[regConfIndex]['name'],
		'object':'regulator_configuration',
		'connect_type':'1',
		'raise_taps':'10',
		'lower_taps':'10',
		'CT_phase':'ABC',
		'PT_phase':'ABC',
		'regulation':'0.10', #Yo, 0.10 means at tap_pos 10 we're 10% above 120V.
		'Control':'MANUAL',
		'control_level':'INDIVIDUAL',
		'Type':'A',
		'tap_pos_A':str(baselineTap),
		'tap_pos_B':str(baselineTap),
		'tap_pos_C':str(baselineTap) }
	# Attach recorders relevant to CVR.
	recorders = [
		{'object': 'collector',
		'file': 'ZlossesTransformer.csv',
		'group': 'class=transformer',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'collector',
		'file': 'ZlossesUnderground.csv',
		'group': 'class=underground_line',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'collector',
		'file': 'ZlossesOverhead.csv',
		'group': 'class=overhead_line',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'recorder',
		'file': 'Zregulator.csv',
		'limit': '0',
		'parent': tree[regIndex]['name'],
		'property': 'tap_A,tap_B,tap_C,power_in.real,power_in.imag'},
		{'object': 'collector',
		'file': 'ZvoltageJiggle.csv',
		'group': 'class=triplex_meter',
		'limit': '0',
		'property': 'min(voltage_12.mag),mean(voltage_12.mag),max(voltage_12.mag),std(voltage_12.mag)'},
		{'object': 'recorder',
		'file': 'ZsubstationTop.csv',
		'limit': '0',
		'parent': tree[swingIndex]['name'],
		'property': 'voltage_A,voltage_B,voltage_C'},
		{'object': 'recorder',
		'file': 'ZsubstationBottom.csv',
		'limit': '0',
		'parent': tree[regIndex]['to'],
		'property': 'voltage_A,voltage_B,voltage_C'} ]
	biggest = 1 + max(tree.keys())
	for index, rec in enumerate(recorders):
		tree[biggest + index] = rec
	# Change constant PF loads to ZIP loads. (See evernote for rationale about 50/50 power/impedance mix.)
	blankZipModel = {'object':'triplex_load',
		'name':'NAMEVARIABLE',
		'base_power_12':'POWERVARIABLE',
		'power_fraction_12':'0.5',
		'impedance_fraction_12':'0.5',
		'power_pf_12':'0.9', #TODO: we can probably get this PF data from the Milsoft loads.
		'impedance_pf_12':'0.97',
		'nominal_voltage':'120',
		'phases':'PHASESVARIABLE',
		'parent':'PARENTVARIABLE'}
	def powerClean(powerStr):
		''' take 3339.39+1052.29j to 3339.39 '''
		return powerStr[0:powerStr.find('+')]
	for key in tree:
		if tree[key].get('object','') == 'triplex_node':
			# Get existing variables.
			name = tree[key].get('name','')
			power = tree[key].get('power_12','')
			parent = tree[key].get('parent','')
			phases = tree[key].get('phases','')
			# Replace object and reintroduce variables.
			tree[key] = copy(blankZipModel)
			tree[key]['name'] = name
			tree[key]['base_power_12'] = powerClean(power)
			tree[key]['parent'] = parent
			tree[key]['phases'] = phases
	# Function to determine how low we can tap down in the CVR case:
	def loweringPotential(baseLine):
		''' Given a baseline end of line voltage, how many more percent can we shave off the substation voltage? '''
		''' testsWePass = [122.0,118.0,200.0,110.0] '''
		lower = int(math.floor((baseLine/114.0-1)*100)) - 1
		# If lower is negative, we can't return it because we'd be undervolting beyond what baseline already was!
		if lower < 0:
			return baselineTap
		else:
			return baselineTap - lower
	# Run all the powerflows.
	powerflows = []
	for doingCvr in [False, True]:
		# For each load level in the tenLoadLevels, run a powerflow with the load objects scaled to the level.
		for desiredLoad in tenLoadLevels:
			# Find the total load that was defined in Milsoft:
			loadList = []
			for key in tree:
				if tree[key].get('object','') == 'triplex_load':
					loadList.append(tree[key].get('base_power_12',''))
			totalLoad = sum([float(x) for x in loadList])
			# Rescale each triplex load:
			for key in tree:
				if tree[key].get('object','') == 'triplex_load':
					currentPow = float(tree[key]['base_power_12'])
					ratio = desiredLoad/totalLoad
					tree[key]['base_power_12'] = str(currentPow*ratio)
			# If we're doing CVR then lower the voltage.
			if doingCvr:
				# Find the minimum voltage we can tap down to:
				newTapPos = baselineTap
				for row in powerflows:
					if row.get('loadLevel','') == desiredLoad:
						newTapPos = loweringPotential(row.get('lowVoltage',114))
				# Tap it down to there.
				# TODO: do each phase separately because that's how it's done in the field... Oof.
				tree[regConfIndex]['tap_pos_A'] = str(newTapPos)
				tree[regConfIndex]['tap_pos_B'] = str(newTapPos)
				tree[regConfIndex]['tap_pos_C'] = str(newTapPos)
			# Run the model through gridlab and put outputs in the table.
			output = gridlabd.runInFilesystem(tree, keepFiles=False)
			p = output['Zregulator.csv']['power_in.real'][0]
			q = output['Zregulator.csv']['power_in.imag'][0]
			s = math.sqrt(p**2+q**2)
			lossTotal = 0.0
			for device in ['ZlossesOverhead.csv','ZlossesTransformer.csv','ZlossesUnderground.csv']:
				for letter in ['A','B','C']:
					r = output[device]['sum(power_losses_' + letter + '.real)'][0]
					i = output[device]['sum(power_losses_' + letter + '.imag)'][0]
					lossTotal += math.sqrt(r**2 + i**2)
			## Entire output:
			powerflows.append({
				'doingCvr':doingCvr,
				'loadLevel':desiredLoad,
				'realPower':p,
				'powerFactor':p/s,
				'losses':lossTotal,
				'subVoltage': (
					output['ZsubstationBottom.csv']['voltage_A'][0] + 
					output['ZsubstationBottom.csv']['voltage_B'][0] + 
					output['ZsubstationBottom.csv']['voltage_C'][0] )/3/60,
				'lowVoltage':output['ZvoltageJiggle.csv']['min(voltage_12.mag)'][0]/2,
				'highVoltage':output['ZvoltageJiggle.csv']['max(voltage_12.mag)'][0]/2 })
	# For a given load level, find two points to interpolate on.
	def getInterpPoints(t):
		''' Find the two points we can interpolate from. '''
		''' tests pass on [tenLoadLevels[0],tenLoadLevels[5]+499,tenLoadLevels[-1]-988] '''
		loc = sorted(tenLoadLevels + [t]).index(t)
		if loc==0:
			return (tenLoadLevels[0],tenLoadLevels[1])
		elif loc>len(tenLoadLevels)-2:
			return (tenLoadLevels[-2],tenLoadLevels[-1])
		else:
			return (tenLoadLevels[loc-1],tenLoadLevels[loc+1])
	# Calculate peak reduction.
	for row in monthData:
		peak = row['histPeak']
		peakPoints = getInterpPoints(peak)
		peakTopBase = [x for x in powerflows if x.get('loadLevel','') == peakPoints[-1] and x.get('doingCvr','') == False][0]
		peakTopCvr = [x for x in powerflows if x.get('loadLevel','') == peakPoints[-1] and x.get('doingCvr','') == True][0]
		peakBottomBase = [x for x in powerflows if x.get('loadLevel','') == peakPoints[0] and x.get('doingCvr','') == False][0]
		peakBottomCvr = [x for x in powerflows if x.get('loadLevel','') == peakPoints[0] and x.get('doingCvr','') == True][0]
		# Linear interpolation so we aren't running umpteen million loadflows.
		x = (peakPoints[0],peakPoints[1])
		y = (peakTopBase['realPower'] - peakTopCvr['realPower'],
			 peakBottomBase['realPower'] - peakBottomCvr['realPower'])
		peakRed = y[0] + (y[1] - y[0]) * (peak - x[0]) / (x[1] - x[0])
		row['peakReduction'] = peakRed
	# Calculate energy reduction and loss reduction based on average load.
	for row in monthData:
		avgEnergy = row['histAverage']
		energyPoints = getInterpPoints(avgEnergy)
		avgTopBase = [x for x in powerflows if x.get('loadLevel','') == energyPoints[-1] and x.get('doingCvr','') == False][0]
		avgTopCvr = [x for x in powerflows if x.get('loadLevel','') == energyPoints[-1] and x.get('doingCvr','') == True][0]
		avgBottomBase = [x for x in powerflows if x.get('loadLevel','') == energyPoints[0] and x.get('doingCvr','') == False][0]
		avgBottomCvr = [x for x in powerflows if x.get('loadLevel','') == energyPoints[0] and x.get('doingCvr','') == True][0]
		# Linear interpolation so we aren't running umpteen million loadflows.
		x = (energyPoints[0], energyPoints[1])
		y = (avgTopBase['realPower'] - avgTopCvr['realPower'],
			avgBottomBase['realPower'] - avgBottomCvr['realPower'])
		energyRed = y[0] + (y[1] - y[0]) * (avgEnergy - x[0]) / (x[1] - x[0])
		row['energyReduction'] = energyRed
		lossY = (avgTopBase['losses'] - avgTopCvr['losses'],
			avgBottomBase['losses'] - avgBottomCvr['losses'])
		lossRed = lossY[0] + (lossY[1] - lossY[0]) * (avgEnergy - x[0]) / (x[1] - x[0])
		row['lossReduction'] = lossRed
	# Multiply by dollars.
	for row in monthData:
		row['energyReductionDollars'] = row['energyReduction'] * (rates['wholesaleEnergyCostPerKwh'] - rates['retailEnergyCostPerKwh'])
		row['peakReductionDollars'] = row['peakReduction'] * rates['peakDemandCost' + row['season'] + 'PerKw']
		row['lossReductionDollars'] = row['lossReduction'] * rates['wholesaleEnergyCostPerKwh']
	# Pretty output
	def plotTable(inData):
		fig = plt.figure(figsize=(20,10))
		plt.axis('off')
		plt.tight_layout()
		plt.table(cellText=[row[1:] for row in inData[1:]], 
			loc = 'center',
			rowLabels = [row[0] for row in inData[1:]],
			colLabels = inData[0])
	def dictalToMatrix(dictList):
		''' Take our dictal format to a matrix. '''
		matrix = [dictList[0].keys()]
		for row in dictList:
			matrix.append(row.values())
		return matrix
	# Powerflow results.
	plotTable(dictalToMatrix(powerflows))
	# Monetary results.
	plotTable(dictalToMatrix(monthData))
	# Graph the money data.
	fig = plt.figure(figsize=(17,10))
	indices = [r['monthName'] for r in monthData]
	d1 = [r['energyReductionDollars'] for r in monthData]
	d2 = [r['lossReductionDollars'] for r in monthData]
	d3 = [r['peakReductionDollars'] for r in monthData]
	ticks = range(len(d1))
	plt.bar(ticks,d1,color='red')
	plt.bar(ticks,d2,color='green')
	plt.bar(ticks,d3,color='blue',yerr=d2)
	plt.xticks([t+0.5 for t in ticks],indices)
	plt.ylabel('Utility Savings ($)')
	# Graph the cumulative savings.
	fig = plt.figure(figsize=(17,8))
	annualSavings = sum(d1) + sum(d2) + sum(d3)
	annualSave = lambda x:(annualSavings - rates['omCost']) * x - rates['capitalCost']
	simplePayback = rates['capitalCost']/(annualSavings - rates['omCost'])
	plt.xlabel('Year After Installation')
	plt.xlim(0,30)
	plt.ylabel('Cumulative Savings ($)')
	plt.plot([0 for x in range(31)],c='gray')
	plt.axvline(x=simplePayback, ymin=0, ymax=1, c='gray', linestyle='--')
	plt.plot([annualSave(x) for x in range(31)], c='green')

def _newTests():
	# Variables
	workDir = pJoin(_omfDir,"data","Model")
	#TODO: fix this tree.
	tree = json.load(open(pJoin(_omfDir, "data", "Feeder", "public", "ABEC Frank LO.json")))["tree"]
	colomaTree = json.load(open(pJoin(_omfDir, "data", "Feeder", "public", "ABEC Columbia.json")))["tree"]
	rates = {"capitalCost": 30000,
		"omCost": 1000,
		"wholesaleEnergyCostPerKwh": 0.06,
		"retailEnergyCostPerKwh": 0.10,
		"peakDemandCostSpringPerKw": 5.0,
		"peakDemandCostSummerPerKw": 10.0,
		"peakDemandCostFallPerKw": 6.0,
		"peakDemandCostWinterPerKw": 8.0}
	colomaMonths = {"janAvg": 914000.0, "janPeak": 1290000.0,
		"febAvg": 897000.00, "febPeak": 1110000.0,
		"marAvg": 731000.00, "marPeak": 1030000.0,
		"aprAvg": 864000.00, "aprPeak": 2170000.0,
		"mayAvg": 1620000.0, "mayPeak": 4580000.0,
		"junAvg": 2210000.0, "junPeak": 5550000.0,
		"julAvg": 3570000.0, "julPeak": 6260000.0,
		"augAvg": 3380000.0, "augPeak": 5610000.0,
		"sepAvg": 1370000.0, "sepPeak": 3740000.0,
		"octAvg": 1030000.0, "octPeak": 1940000.0,
		"novAvg": 1020000.0, "novPeak": 1340000.0,
		"decAvg": 1030000.0, "decPeak": 1280000.0}
	friendshipMonths = {"janAvg": 2740000.0, "janPeak": 4240000.0,
		"febAvg": 2480000.0, "febPeak": 3310000.0,
		"marAvg": 2030000.0, "marPeak": 2960000.0,
		"aprAvg": 2110000.0, "aprPeak": 3030000.0,
		"mayAvg": 2340000.0, "mayPeak": 4080000.0,
		"junAvg": 2770000.0, "junPeak": 5810000.0,
		"julAvg": 3970000.0, "julPeak": 6750000.0,
		"augAvg": 3270000.0, "augPeak": 5200000.0,
		"sepAvg": 2130000.0, "sepPeak": 4900000.0,
		"octAvg": 1750000.0, "octPeak": 2340000.0,
		"novAvg": 2210000.0, "novPeak": 3550000.0,
		"decAvg": 2480000.0, "decPeak": 3370000.0}
	inData = { "modelName": "Automated staticCVR Testing",
		"modelType": "cvrStatic",
		"user": "admin", # Really only used with web.py.
		"runTime": "" }
	# modelLoc = pJoin(workDir, inData["user"], inData["modelName"])
	# Hmmm, might need to show plots.
	# plt.show()
	# # Blow away old test results if necessary.
	# try:
	# 	shutil.rmtree(modelLoc)
	# except:
	# 	# No previous test results.
	# 	pass
	# # No-input template.
	# renderAndShow()
	# # Create a model.
	# create(workDir, inData)
	# # Show the model (should look like it's running).
	# renderAndShow(modelDir=modelLoc)
	# # Run the model.
	# run(modelLoc)
	# # Show the output.
	# renderAndShow(modelDir=modelLoc)
	# # # Delete the model.
	# # time.sleep(2)
	# # shutil.rmtree(modelLoc)

def _tests():
	renderAndShow()

if __name__ == '__main__':
	_newTests()