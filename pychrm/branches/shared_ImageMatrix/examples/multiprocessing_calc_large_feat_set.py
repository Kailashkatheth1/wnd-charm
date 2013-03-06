#!/usr/bin/env python
from pychrm.FeatureSet import *
import multiprocessing as mp
import logging

#================================================================
def ConcurrentTransformFunc( tform_name, input_shmem_name ):
	"""returns the mmap path to the transformed pixel plane """

	mp.log_to_stderr()
	logger = mp.get_logger()
	logger.setLevel( logging.INFO )
	import os
	try:
		print "<<<<<<<<<<<Child pid {}: attempting transform {} on input {}".format(
				os.getpid(), tform_name, input_shmem_name )

		original = pychrm.SharedImageMatrix()
		original.fromCache( input_shmem_name )
		if original.csREAD != original.Status(): 
			raise ValueError( 'Could not build an SharedImageMatrix from {0}, check the file.'.\
												 format( input_shmem_name ) )

		tform = Transforms[ tform_name ]
		ret_px_plane = original.transform( tform )

		original.DisableDestructorCacheCleanup(True)
		ret_px_plane.DisableDestructorCacheCleanup(True)
		ret_px_plane_shmem_name = ret_px_plane.GetShmemName()

		print ">>>>>>>>>>>>Child pid {}: input {}, transformed \"{}\" = {}".format(
				os.getpid(), input_shmem_name, tform_name, ret_px_plane_shmem_name )

	except KeyboardInterrupt:
		print "ConcurrentTransformFunc: Caught Keyboard interrupt inside child process {}".format(
				os.getpid() )
		raise

#================================================================
def ConcurrentFeatCalcFunc( input_shmem_name, alg_name, feature_array, offset):
	"""Perform the feature calculation and put into the feature matrix"""

	mp.log_to_stderr()
	logger = mp.get_logger()
	logger.setLevel( logging.INFO )

	try:
		print "<<<<<<<<<<<Child pid {}: attempting FEATURE CALCULATION {} on input {}".format(
				os.getpid(), alg_name, input_shmem_name )
		
		original = pychrm.SharedImageMatrix()
		if 1 != original.fromCache( input_shmem_name ):
			raise ValueError( 'Could not build an SharedImageMatrix from {0}, check the file.'.\
												 format( input_px_plane ) )

		alg = Algorithms[ alg_name ]
		num_features = alg.n_features
		feature_array[ offset : offset + num_feat ]  = alg.calculate( input_px_plane )

		print ">>>>>>>>>>>>Child pid {}: input {}, calculated features {}".format(
				os.getpid(), input_shmem_name, alg_name  )

	except KeyboardInterrupt:
		print "ConcurrentFeatCalcFunc: Caught Keyboard interrupt inside child process {}".format(
				os.getpid() )
		raise

#================================================================
def GenerateWorkPlan( featuregroup_strings ):
	"""identify the required transforms and the order in which they need to occur"""
	# FIXME: Two levels of transforms hardcoded for now
	# ASSUMPTION: featuregroup string list coming in contains only unique strings

	first_round_tforms = set()
	second_round_tforms = set()
	parsed_algorithms = []
	feature_names = []

	for fg_string in featuregroup_strings:
		if fg_string.startswith( '#' ):
			continue
		string_rep = fg_string.rstrip( ")" )
		parsed = string_rep.split( ' (' )
		alg_name = parsed[0]

		for i in range( Algorithms[ alg_name ].n_features ):
			feature_names.append( fg_string + ' [' + str(i) + ']' )
		tform_list = parsed[1:]
		try:
			tform_list.remove( "" )
		except ValueError:
			pass

		# Make sure all transforms mentioned are known to pychrm
		if len(tform_list) != 0:
			for tform in tform_list:
				if tform not in Transforms:
					raise KeyError( "Don't know about a transform named {0}".format( tform ) )

		if len( tform_list ) > 1:
			# reverse() does an in-place list reversal that returns None 
			tform_list.reverse()
			second_round_tforms.add( tuple( tform_list ) )
			parsed_algorithms.append( ( alg_name, ' '.join( tform_list ) )  )
		elif len( tform_list ) == 1:
			first_round_tforms.add( tform_list[0] )
			parsed_algorithms.append( (alg_name, tform_list[0]) )
		else:
			parsed_algorithms.append( (alg_name, "") )

	return first_round_tforms, second_round_tforms, parsed_algorithms, feature_names

#================================================================
if __name__ == '__main__':

	import sys

	input_tif = sys.argv[1]
	num_cpus = 2
	pool = mp.Pool( num_cpus )

	original = pychrm.SharedImageMatrix()
	if 1 != original.OpenImage( input_tif , 0, None, 0, 0 ):
		raise ValueError( 'Could not build an SharedImageMatrix from {0}, check the file.'.\
							 format( path_to_image ) )
	else:
		print "successfully loaded image"

	pixel_planes = {}
	pp_shmem_names = {}
	original_shmem_name = original.GetShmemName()
	pp_shmem_names[ "" ] = original_shmem_name

	work_order = large_featureset_featuregroup_strings.split( '\n' )
	first_round_tforms, second_round_tforms, algs, feat_names = GenerateWorkPlan( work_order )

	try:
		# Round 1: Asynchronously fire off first round of transforms to the pool
		results = []
		for tform_name in first_round_tforms:
			fn_args = ( tform_name, original_shmem_name )
			res = pool.apply_async( ConcurrentTransformFunc, fn_args )
			results.append( ( tform_name, res ) )

		# Block on completion of round 1
		#for tform_name, res in results:
			res.get()
			new_ShImMat = pychrm.SharedImageMatrix()
			new_ShImMat.fromCache( original_shmem_name, tform_name )
			pixel_planes[ tform_name ] = new_ShImMat
			#new_ShImMat.DisableDestructorCacheCleanup(False)
			pp_shmem_names[ tform_name ] = new_ShImMat.GetShmemName()


		print "\n\n\n************************************ROUND 1 COMPLETE*************************\n\n\n"
		# Round 2: Asynchronously fire off second round of transforms to the pool
		results = []
		for first_tform_name, second_tform_name in second_round_tforms:
			first_tform_shmem_addr = pp_shmem_names[ first_tform_name ]
			fn_args = ( second_tform_name, first_tform_shmem_addr )
			res = pool.apply_async( ConcurrentTransformFunc, fn_args )
			results.append( ( first_tform_shmem_addr, first_tform_name, second_tform_name, res ) )

		# Block on completion of round 2
		#for first_tform_shmem_addr, first_tform_name, second_tform_name, res in results:
			res.get()
			new_ShImMat = pychrm.SharedImageMatrix()
			new_ShImMat.fromCache( first_tform_shmem_addr, tform_name )
			#new_ShImMat.DisableDestructorCacheCleanup(False)
			tform_compound_name = first_tform_name + ' ' + second_tform_name
			pixel_planes[ tform_compound_name ] = new_ShImMat
			pp_shmem_names[ tform_compound_name ] = new_ShImMat.GetShmemName()


		print "\n\n\n************************************ROUND 2 COMPLETE*************************\n\n\n"

		print "*****************{}****************".format( len( pixel_planes ) )
		# After all transforms are completed, all dependencies have been removed.
		# Asynchronously fire off all feature calculation and block until completion

		
		image_index = 0 # will be incremented when we start looping over images
		num_images = 1
		num_features = len( feat_names )
		import ctypes 

		shared_array_base = mp.Array( ctypes.c_double, num_images * num_features )

		column_offset = 0
		results = []
		for algname, required_tform in algs:
			offset = image_index * self.num_features + column_offset
			required_pp_shmem_name = pp_shmem_names[ required_tform ]
			fn_args = ( required_shmem_name, algname, shared_array_base, offset )
			res = pool.apply_async( ConcurrentFeatCalcFunc, fn_args ) 
			results.append( (algname, required_tform, required_pp_shmem_name, res ) )
			column_offset += Algorithms[ algname ].n_features

		# Block:
		for algname, tform_name, tform_shmem_name, res in results:
			print "receiving results from {} ({}) shmem {}".format(
				algname, tform_name, tform_shmem_name )
			res.get()

		print shared_array_base

	except KeyboardInterrupt:
		print "You pressed Ctrl-C"

