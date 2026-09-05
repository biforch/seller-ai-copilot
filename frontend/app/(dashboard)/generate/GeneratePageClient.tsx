'use client';


import { useState, useEffect } from 'react';

import { useRouter, useSearchParams } from 'next/navigation';

import { apiClient } from '@/app/api/client';


import { AnalyzerResultView } from '@/components/features/AnalyzerResult';

import { ListingResultView } from '@/components/features/ListingResult';

import { ProductForm } from '@/components/features/ProductForm';


import { useGenerate } from '@/hooks/useGenerate';

import { useProjects } from '@/hooks/useProjects';

import { buildReviewPath } from '@/lib/listing-proposals';


import type {
  AnalyzeFormData,
  GenerateFormData,
  ProductDetail,
} from '@/types';



type Tab =
  | 'generate'
  | 'analyze';





export function GeneratePageClient(){


  const searchParams =
    useSearchParams();

  const productId =
    searchParams.get(
      'product_id'
    );

  const amazonListingId = searchParams.get('amazon_listing_id');

  const sessionKey = productId
    ? `product:${productId}:${amazonListingId ?? ''}`
    : 'blank';

  return <GeneratePageClientSession key={sessionKey} />;

}


function GeneratePageClientSession(){


  const router = useRouter();

  const searchParams =
    useSearchParams();


  const {
    projects,
    isLoading: projectsLoading,
    fetchProjects,
  } = useProjects();


  useEffect(()=>{

    fetchProjects({ page_size: 100 });

  },[fetchProjects]);



  const projectId =
    searchParams.get(
      'project_id'
    );

  const productId =
    searchParams.get(
      'product_id'
    );

  const amazonListingId = searchParams.get('amazon_listing_id');

  const [productLoadError, setProductLoadError] = useState<string | null>(null);
  const [productLoading, setProductLoading] = useState(Boolean(productId));
  const [loadedProductId, setLoadedProductId] = useState<string | null>(null);




  const [
    tab,
    setTab
  ] = useState<Tab>(
    'generate'
  );




  const [
    formData,
    setFormData
  ] = useState<GenerateFormData>(() => (
    productId
      ? {
          name:'',
          category:'',
          market:'USA',
          platform:'Amazon'
        }
      : {
          project_id:
            projectId || undefined,
          name:'',
          category:'',
          market:'USA',
          platform:'Amazon'
        }
  ));





  const [
    analyzeData,
    setAnalyzeData
  ] = useState<AnalyzeFormData>({

    project_id:
      projectId || undefined,

    title:'',

    reviews:0,

    rating:4,

    description:''

  });





  const visibleFormData: GenerateFormData = productId
    ? formData
    : {
        ...formData,
        project_id: projectId || undefined,
      };

  const visibleAnalyzeData: AnalyzeFormData = productId
    ? analyzeData
    : {
        ...analyzeData,
        project_id: projectId || undefined,
      };

  useEffect(()=>{
    if (!productId) {
      return;
    }
    const controller = new AbortController();
    const listingId = amazonListingId;

    void apiClient.get<ProductDetail>(`/products/${encodeURIComponent(productId)}`, {
      signal: controller.signal,
    }).then((product) => {
      if (controller.signal.aborted) return;
      setFormData({
        project_id: product.project?.id ?? undefined,
        product_id: product.id,
        amazon_listing_id: listingId || undefined,
        name: product.name,
        category: product.category ?? 'General',
        market: product.market,
        platform: product.platform,
        target_customer: product.target_customer ?? undefined,
        advantages: product.advantages ?? undefined,
      });
      setLoadedProductId(product.id);
      setProductLoading(false);
      if (product.project?.id) {
        const canonicalParams = new URLSearchParams({
          product_id: product.id,
          project_id: product.project.id,
        });
        if (listingId) canonicalParams.set('amazon_listing_id', listingId);
        router.replace(`/generate?${canonicalParams.toString()}`);
      }
    }).catch(() => {
      if (!controller.signal.aborted) {
        setProductLoadError('The linked product could not be loaded. Return to Amazon and choose another product.');
        setProductLoading(false);
      }
    });

    return () => controller.abort();
  }, [amazonListingId, productId, router]);






  const {

    isLoading,

    error,

    listingResult,

    analyzeResult,

    generateListing,

    analyzeListing,

    reset


  } = useGenerate();







  const handleGenerate =
    async()=>{

      if (productId && (productLoading || productLoadError || loadedProductId !== productId)) {
        return;
      }


      await generateListing(
        visibleFormData
      );


    };







  const handleAnalyze =
    async()=>{


      await analyzeListing(
        visibleAnalyzeData
      );


    };









  return (

    <div
      className="
      max-w-7xl
      mx-auto
      px-4
      py-8
      "
    >



      <div className="mb-8">


        <h1
          className="
          text-3xl
          font-bold
          text-gray-900
          "
        >

          AI Generate

        </h1>

        {productId && loadedProductId === productId && !productLoading && !productLoadError && (
          <p className="mt-2 rounded-lg border border-purple-200 bg-purple-50 px-3 py-2 text-sm text-purple-700">
            Listnara product loaded from your Amazon listing link. Generated content will remain a review proposal and will not be published to Amazon.
          </p>
        )}

        {amazonListingId && loadedProductId === productId && !productLoading && !productLoadError && (
          <p className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">
            The latest saved Amazon catalog summary will be used as untrusted factual reference. Listnara will still create a review proposal only.
          </p>
        )}

        {productLoading && (
          <p className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
            Loading your linked Listnara product…
          </p>
        )}

        {productLoadError && (
          <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {productLoadError}
          </p>
        )}



        <div className="mt-3 max-w-sm">

          <label className="block text-sm text-gray-600 mb-1">
            Project
          </label>

          <select

            value={visibleFormData.project_id || ''}

            onChange={(e)=>{

              const value = e.target.value;

              setFormData((current) => ({
                ...current,
                project_id: value || undefined,
                product_id: undefined,
              }));

              router.replace(
                value
                ? `/generate?project_id=${value}`
                : '/generate'
              );

            }}

            className="
            w-full
            border
            rounded-lg
            px-3
            py-2
            bg-white
            "

          >

            <option value="" disabled>
              {
                projectsLoading
                ? 'Loading projects...'
                : 'Select a project'
              }
            </option>

            {
              projects.map(p=>(

                <option key={p.id} value={p.id}>
                  {p.name}
                </option>

              ))
            }

          </select>

          {
            !projectsLoading &&
            projects.length === 0 &&

            <p className="text-sm text-amber-600 mt-2">
              You don&apos;t have any projects yet.{' '}
              <button
                type="button"
                onClick={()=>router.push('/projects/create')}
                className="underline"
              >
                Create one
              </button>
              {' '}before generating.
            </p>
          }

        </div>


      </div>







      <div
        className="
        flex
        gap-3
        mb-6
        "
      >


        <button

          onClick={()=>{

            setTab('generate');

            reset();

          }}

          className={

            `
            px-4
            py-2
            rounded-lg
            font-medium

            ${
              tab==='generate'
              ?
              'bg-blue-600 text-white'
              :
              'bg-white border'
            }

            `
          }


        >

          Generate Listing

        </button>





        <button


          onClick={()=>{


            setTab('analyze');

            reset();


          }}


          className={

            `
            px-4
            py-2
            rounded-lg
            font-medium

            ${
              tab==='analyze'
              ?
              'bg-blue-600 text-white'
              :
              'bg-white border'
            }

            `
          }


        >

          Analyze Competitor

        </button>



      </div>







      {
        error &&


        <div

          className="
          bg-red-50
          text-red-600
          rounded-lg
          p-3
          mb-5
          "

        >

          {error}


        </div>

      }









      <div

        className="
        grid
        lg:grid-cols-2
        gap-8
        "

      >





        <div

          className="
          bg-white
          border
          rounded-xl
          p-6
          "

        >



        {
          tab==='generate'


          ?


          <ProductForm

            key={visibleFormData.product_id ?? 'new-product'}


            data={visibleFormData}


            onChange={setFormData}


            onSubmit={handleGenerate}


            isLoading={
              isLoading ||
              productLoading ||
              Boolean(productId && (productLoadError || loadedProductId !== productId))
            }


          />



          :



          <form


            onSubmit={(e)=>{

              e.preventDefault();

              handleAnalyze();

            }}


            className="
            space-y-5
            "

          >




            <div>

              <label className="block text-sm mb-1">

                Competitor Title

              </label>


              <input


                value={
                  analyzeData.title
                }


                onChange={
                  e=>
                  setAnalyzeData({

                    ...analyzeData,

                    title:e.target.value

                  })
                }


                className="
                w-full
                border
                rounded-lg
                px-4
                py-2
                "

                required


              />


            </div>






            <div
              className="
              grid
              grid-cols-2
              gap-4
              "
            >


              <div>


                <label className="block text-sm mb-1">

                  Reviews

                </label>



                <input

                  type="number"


                  value={
                    analyzeData.reviews
                  }


                  onChange={
                    e=>
                    setAnalyzeData({

                      ...analyzeData,

                      reviews:
                        Number(e.target.value)

                    })
                  }


                  className="
                  w-full
                  border
                  rounded-lg
                  px-4
                  py-2
                  "

                />


              </div>





              <div>


                <label className="block text-sm mb-1">

                  Rating

                </label>



                <input

                  type="number"

                  step="0.1"

                  max="5"

                  value={
                    analyzeData.rating
                  }


                  onChange={
                    e=>
                    setAnalyzeData({

                      ...analyzeData,

                      rating:
                      Number(e.target.value)

                    })
                  }


                  className="
                  w-full
                  border
                  rounded-lg
                  px-4
                  py-2
                  "

                />


              </div>


            </div>







            <div>


              <label className="block text-sm mb-1">

                Description

              </label>



              <textarea


                value={
                  analyzeData.description
                }


                onChange={
                  e=>
                  setAnalyzeData({

                    ...analyzeData,

                    description:e.target.value

                  })
                }



                className="
                w-full
                border
                rounded-lg
                px-4
                py-2
                h-32
                "


              />


            </div>







            <button

              disabled={isLoading || !projectId}


              className="
              w-full
              bg-blue-600
              text-white
              py-2.5
              rounded-lg
              disabled:opacity-50
              "

            >

              {
                isLoading
                ?
                'Analyzing...'
                :
                !projectId
                ?
                'Select a project first'
                :
                'Analyze'
              }


            </button>



          </form>



        }



        </div>









        <div>


          {
            listingResult &&


            <div className="space-y-4">

            <ListingResultView

              result={
                listingResult
              }

            />

            {listingResult.proposal && listingResult.product_id && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <p className="text-sm text-blue-900 mb-3">
                  A reviewable AI proposal was created. Open the review workspace to accept or reject
                  individual fields before approving a new listing version.
                </p>
                <button
                  type="button"
                  onClick={() =>
                    router.push(
                      buildReviewPath(listingResult.product_id, listingResult.proposal!.id),
                    )
                  }
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Review AI Proposal
                </button>
              </div>
            )}

            </div>

          }






          {
            analyzeResult &&


            <AnalyzerResultView

              result={
                analyzeResult
              }

            />

          }





          {
            !listingResult &&
            !analyzeResult &&


            <div

              className="
              bg-white
              border
              rounded-xl
              p-8
              text-center
              text-gray-400
              "

            >

              Result will appear here


            </div>


          }




        </div>






      </div>





    </div>


  );

}
