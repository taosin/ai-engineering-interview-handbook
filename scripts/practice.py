#!/usr/bin/env python3
"""Filter or reproducibly sample the source-backed interview question bank."""
import argparse
import random
from validate import load_data, validate_data


def main():
    qs,ss,cat=load_data();validate_data(qs,ss,cat)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role',choices=[r['name'] for r in cat['roles']])
    parser.add_argument('--topic',choices=[t['id'] for t in cat['topics']])
    parser.add_argument('--type',dest='question_type',choices=list(cat['question_types']))
    parser.add_argument('--query',help='Case-insensitive question text search')
    parser.add_argument('--limit',type=int,default=None)
    parser.add_argument('--sample',type=int,default=None)
    parser.add_argument('--seed',type=int,default=None)
    args=parser.parse_args()
    if any(n is not None and n<1 for n in (args.limit,args.sample)):
        parser.error('--limit and --sample must be positive')
    selected=[q for q in qs if (not args.role or args.role in q['roles'])
              and (not args.topic or args.topic==q['topic'])
              and (not args.question_type or args.question_type==q['question_type'])
              and (not args.query or args.query.lower() in q['question'].lower())]
    if args.sample is not None:selected=random.Random(args.seed).sample(selected,min(args.sample,len(selected)))
    if args.limit is not None:selected=selected[:args.limit]
    print(f'选中 {len(selected)} 道题。题型与岗位标签为编者建议。')
    for q in selected:
        print(f"\n{q['id']} [{cat['question_types'][q['question_type']]}] {q['question']}")
        print('来源：'+', '.join(q['source_ids'])+'；详见 SOURCES.md')

if __name__=='__main__':main()
