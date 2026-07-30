'use client';


import {
  useCallback,
  useState
} from 'react';


import {
  apiClient
} from '@/app/api/client';


import type {

  GenerateFormData,

  AnalyzeFormData,

  ListingResult,

  AnalyzeResult

} from '@/types';





export function useGenerate(){


const [
  isLoading,
  setIsLoading
]=useState(false);



const [
  error,
  setError
]=useState<string|null>(null);




const [
  listingResult,
  setListingResult
]=useState<ListingResult|null>(null);




const [
  analyzeResult,
  setAnalyzeResult
]=useState<AnalyzeResult|null>(null);







const generateListing =
useCallback(

async(
 data:GenerateFormData
)=>{


 setIsLoading(true);

 setError(null);



 try{


 const result =
 await apiClient.post<ListingResult>(

   '/generate/listing',

   data

 );



 setListingResult(result);

 setAnalyzeResult(null);



 return result;



 }catch(err){


 const msg =
 err instanceof Error
 ?
 err.message
 :
 'Generation failed';



 setError(msg);


 throw err;



 }finally{


 setIsLoading(false);


 }


},

[]);









const analyzeListing =
useCallback(

async(
 data:AnalyzeFormData
)=>{


 setIsLoading(true);

 setError(null);



 try{


 const result =
 await apiClient.post<AnalyzeResult>(

   '/generate/analyze',

   data

 );



 setAnalyzeResult(result);

 setListingResult(null);



 return result;



 }catch(err){


 const msg =
 err instanceof Error
 ?
 err.message
 :
 'Analysis failed';



 setError(msg);



 throw err;



 }finally{


 setIsLoading(false);


 }



},

[]);









const reset =
useCallback(()=>{


 setListingResult(null);

 setAnalyzeResult(null);

 setError(null);


},[]);






return {


 isLoading,

 error,

 listingResult,

 analyzeResult,


 generateListing,

 analyzeListing,


 reset


};



}