# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Geogrpahic Service Area Generation.py
# Created by: Mark Pooley
# Description: 
# This script takes a shape file, unique identifier field for features in the shape file, and a seed shape file
# and generates the most compact service areas possible .
# ---------------------------------------------------------------------------
import math
import arcpy
import sys
import traceback
from arcpy import env
env.workspace = arcpy.GetParameterAsText(0)
env.overWriteOutput = True


zipCodes = arcpy.GetParameterAsText(1)
ZCTA_Field = arcpy.GetParameterAsText(2)
seeds = arcpy.GetParameterAsText(3)



#Add Field to track what ZipCodes have been assigend to a particular Service Area
arcpy.AddField_management(zipCodes,"Assigned_To","TEXT")
Assigned_To = "Assigned_To"

#create a feature layer so the polygons can be selectec
FeatureLayer = arcpy.MakeFeatureLayer_management(zipCodes,"Temporary_Layer")

#selecting initial seed zip codes that contain the seed point files
seedSelection = arcpy.SelectLayerByLocation_management(FeatureLayer,"INTERSECT",seeds,"#","NEW_SELECTION")

#Populating the Initial 'Assigned_To' fields
with arcpy.da.UpdateCursor(seedSelection,[ZCTA_Field,Assigned_To]) as Cursor_Seed:
    arcpy.AddMessage("Populating Initial 'Assigned_To' Fields...")
    for row in Cursor_Seed:
        #populate 'Assigned_To' fields
        row[1] = row[0] 

        Cursor_Seed.updateRow(row)

#update seed perimter and area geomtries
arcpy.da.UpdateCursor(seedSelection,["SHAPE@AREA","SHAPE@LENGTH"])


#Selecting the starting polygon features containing the seeds which will be used
#for near calculation
seedPoly = arcpy.Select_analysis(seedSelection,"Temp_SeedPolygons","")

#Create a seed list and populate it with zip code IDs
seedList = []
with arcpy.da.SearchCursor(seedPoly,[ZCTA_Field]) as cursor:
    for row in cursor:
        seedList.append(str(row)[3:8])

arcpy.AddMessage("Seed zipcodes: " + str(seedList))



#Select and get count of unassigned features
#get count of features that are in need of assigment
FeatureCount = int(arcpy.GetCount_management(zipCodes).getOutput(0))
arcpy.AddMessage("Unassigned features: " + str(FeatureCount))
ProgressorLength = FeatureCount - len(seedList) 
FeatureCount_Unassigned = ProgressorLength
seedListLength = len(seedList)

#set up a progressor for the loop(s)
arcpy.SetProgressor("step","Calculating compactness for each source and neighbor...",0,ProgressorLength,len(seedList))

loopCounter = 0
while FeatureCount_Unassigned > 0:

    arcpy.SetProgressorLabel("Clearing selections...")
    arcpy.SelectLayerByAttribute_management(FeatureLayer,"Clear_Selection")

    #arcpy.AddMessage("Current iteration: " + str(loopNumber))
    adjacentSelection = arcpy.SelectLayerByLocation_management(FeatureLayer,"BOUNDARY_TOUCHES",seedPoly,"#","NEW_SELECTION")

    #create table of polygon neightbors on the adjeacent selection
    arcpy.SetProgressorLabel("Generating table of neighbors to seeds and calculating shared perimeter...")
    
    NeighborTable = arcpy.PolygonNeighbors_analysis(adjacentSelection,"Temp_NeighborTable","ZIP;Shape_Length;Shape_Area;Assigned_To","NO_AREA_OVERLAP","BOTH_SIDES","#","METERS","SQUARE_METERS")


    """
    Zipcodes_Unassigned = arcpy.SelectLayerByAttribute_management(FeatureLayer,"NEW_SELECTION",'"Assigned_To" IS NULL')
    FeatureCount_Unassigned  = arcpy.GetCount_management(Zipcodes_Unassigned)
    """
    #Add field for compactness calculation
    arcpy.AddField_management(NeighborTable,"Compact","DOUBLE")


    #NeighborTable Cursor that calculates the compactness of each option within the neighbor table. Compactness being defined as the area of the two neighbors
    #compared to the area of a circle with the same permiter as the two perimeters combined.
    with arcpy.da.UpdateCursor(NeighborTable,["src_Shape_Length","nbr_Shape_Length","src_Shape_Area","nbr_Shape_Area","LENGTH","Compact"])as NBR_cursor:
        for row in NBR_cursor:
            Circ = (row[0] + row[1]-row[4])
            R = Circ/(2*math.pi)
            row[5] = (row[2] + row[3])/(math.pi * (R**2))
            #row[5] = ((row[0] + row[1] - row[4]) / (row[2] + row[3]))
            NBR_cursor.updateRow(row)

    #dictionary that keeps track of the seed polygon, and where it's assigned to

    #create an assignment dictionary that will track assignments and evaluate best assignment as nbrs can potentially be assigned to multiple sources
    Seed_NBR_Dict = {}

    #create a remove list that will have service areas appended to it that are surrounded by other service areas.
    removeList = []

    #update Progressor position
    arcpy.SetProgressorPosition()

    #iterate through the seed list to find the best adjacent feature to add to the seed feature. 
    arcpy.SetProgressor("step","Assigning adjacent polygons to seeds",0,len(seedList),1)  
    for item  in seedList:

    
        #Temporary dictionary that will contain the best neighbor for each seed
        tempDict = {}
        currentSeed = item

        arcpy.SetProgressorLabel("Determining best fit for " + str(currentSeed) + "...")

        #whereclauset to select each set of neighbors for each seed
        whereClause_Neighbor = 'src_ZIP = ' + "'" + currentSeed + "'"
    

        #temporary neighbor list and compactness variable
        nbrList = []
        
        #iterate through all features that have the current seed as a source zip and evaluate thier compactness.
        with arcpy.da.SearchCursor(NeighborTable,["nbr_ZIP","nbr_Assigned_To","Compact"],whereClause_Neighbor) as Cursor_Compact:
            for row in Cursor_Compact:
                if row[1] == None:
                    tempDict[str(row[0])] = float(row[2])

        #check if dictionary is empty. If so, this means service areas is surrounded by other service areas and can be removed from the list
        if bool(tempDict) == False:
            #if empty append to removeList
            removeList.append(currentSeed)
            #remove current seed from seed list
            del seedList[seedList.index(currentSeed)]
            
            arcpy.AddMessage("Seed Zip: " + str(currentSeed) + " removed due to being bounded by other service areas")

        else:
            maxCompact = (max(tempDict, key = tempDict.get))    
        
            #check if the best fit is in the seedlist. If it is, remove it and find imin compact again.
            if maxCompact in seedList or maxCompact in removeList:
                tempDict.pop(currentSeed,0)
                arcpy.AddMessage(currentSeed + "removed from temp dictionary")

            #Recalculate the best fit 
            maxCompact = (max(tempDict, key = tempDict.get))   

            
            
            if bool(tempDict) == True:
                #need to check if the max compact has already shown up in the NBR dictionary, if it has check to make sure the assignment is still the best of all available options
                #if Seed_NBR_Dict.has_key(maxCompact) == True:
                #    if Seed_NBR_Dict[]
                #if temp dictionary is not empty, assign the best neighbor to the current seed.
                Seed_NBR_Dict[currentSeed] = maxCompact

                arcpy.SetProgressorLabel("updating 'Assigned_To' field...")
                #update "Assigned_To" using the dictionary
                whereClause_Assign = ZCTA_Field + " = " + "'" + str(Seed_NBR_Dict[currentSeed]) + "'"
                #arcpy.AddMessage("Assigned SQL clause: " + whereClause_Assign)

               
                #Updating "Zip" field so queries work throughout the loop
                with arcpy.da.UpdateCursor(FeatureLayer,[ZCTA_Field, Assigned_To],whereClause_Assign) as Cursor_AssignedTo:
                    for row in Cursor_AssignedTo:
                    
                        row[1] = currentSeed
                                                                           
                        Cursor_AssignedTo.updateRow(row)
                with arcpy.da.UpdateCursor(zipCodes,[ZCTA_Field, Assigned_To],whereClause_Assign) as zipCursor:
                    for row in zipCursor:
                        row[1] = currentSeed
                        zipCursor.updateRow(row)

        
       
                #Updating "Zip" field so queries work throughout the loop
                with arcpy.da.UpdateCursor(FeatureLayer,[ZCTA_Field, Assigned_To],whereClause_Assign) as Cursor_AssignedTo:
                    for row in Cursor_AssignedTo:
                    
                        row[1] = currentSeed
                                                                           
                        Cursor_AssignedTo.updateRow(row)
        arcpy.SetProgressorPosition()
        arcpy.ResetProgressor()

    
    
  
    #Select rows within feature that aren't null - meaning they have been assigned to a seed
    seedPoly = arcpy.SelectLayerByAttribute_management(FeatureLayer,"NEW_SELECTION",'"Assigned_To" IS NOT NULL')

    #create a new feature class for those not null features
    seedPoly = arcpy.Select_analysis(seedPoly,"Temp_NotNull","")

    #dissolve the newly created feature class by the "Assigned_To" field
    seedPoly = arcpy.Dissolve_management(seedPoly,"Temp_SeedPolygons","Assigned_To","#","MULTI_PART","DISSOLVE_LINES")
    
    
    #find all those that aren't 
    Zipcodes_Unassigned = arcpy.Erase_analysis(zipCodes,seedPoly,"Temp_Zipcodes_Unassigned")
    Zip_Seeds_Merged = arcpy.Merge_management([Zipcodes_Unassigned,seedPoly],"Temp_ZipCodes")
    
    
    with arcpy.da.UpdateCursor(Zip_Seeds_Merged,["ZIP","Assigned_To"]) as Cursor_merged:
        for row in Cursor_merged:
            if row[0] != None:
                pass
            else:
                row[0] = row[1]
                
                Cursor_merged.updateRow(row)
           
    #Establish loop for iterating through seeds and assigning neighbors based on compactness calculation
    FeatureCount_Unassigned = int(arcpy.GetCount_management(Zipcodes_Unassigned).getOutput(0)) #arcpy.GetCount_management(Zipcodes_Unassigned)
    FeatureLayer = arcpy.MakeFeatureLayer_management(Zip_Seeds_Merged,"Temporary_Layer")
    arcpy.AddMessage("Number of features unassigned: "+ str(FeatureCount_Unassigned))
    
    #update Progressor Position
    arcpy.SetProgressorPosition()

    if FeatureCount_Unassigned == 0:
        copyFeatures = arcpy.CopyFeatures_management(FeatureLayer,"Final_Output","#","0","0","0")
        arcpy.AddMessage("Removing Temporary files...")
        TempFeatures = arcpy.ListFeatureClasses("Temp*")
        TempList = []
        for feature in TempFeatures:
            if "Temp" in feature:
                arcpy.Delete_management(feature)
        break



    
  
arcpy.AddMessage("Process Complete!")




